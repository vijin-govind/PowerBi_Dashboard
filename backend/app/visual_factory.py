"""Create brand-new visuals for both report formats.

For the legacy format we delegate to pbix-mcp's tested binding compiler
(``PBIXBuilder._build_layout``) so the generated container matches what Power
BI Desktop expects. For PBIR we write a ``visual.json`` following Microsoft's
public visualContainer schema.
"""

from __future__ import annotations

import json
import uuid

from .fields import field_to_expr, native_ref, query_ref, title_objects

PBIR_VISUAL_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/"
    "visualContainer/2.4.0/schema.json"
)

_PANDAS_TO_AMO = {
    "object": "String",
    "str": "String",
    "string": "String",
    "int64": "Int64",
    "Int64": "Int64",
    "float64": "Double",
    "bool": "Boolean",
    "datetime64[ns]": "DateTime",
}


def amo_type(dtype: str | None) -> str:
    if not dtype:
        return "String"
    if dtype.startswith("datetime"):
        return "DateTime"
    return _PANDAS_TO_AMO.get(dtype, "String")


def _textbox_objects(text: str) -> dict:
    paragraphs = [{"textRuns": [{"value": line}]} for line in (text or "").split("\n")]
    return {"general": [{"properties": {"paragraphs": paragraphs}}]}


def new_legacy_container(v: dict, schema: dict) -> dict:
    from pbix_mcp.builder import PBIXBuilder  # heavy import, keep lazy

    b = PBIXBuilder()
    b._tables = [
        {
            "name": t["name"],
            "columns": [{"name": c["name"], "data_type": amo_type(c.get("dataType"))} for c in t.get("columns", [])],
        }
        for t in schema.get("tables", [])
    ]
    b._measures = [
        {"name": m["name"], "table": t["name"]} for t in schema.get("tables", []) for m in t.get("measures", [])
    ]
    roles: dict[str, list[dict]] = {}
    for f in v.get("fields", []):
        if f.get("kind") == "measure":
            spec = {"measure": f["name"]}
        elif f.get("kind") in ("column", "aggregation"):
            spec = {"table": f["table"], "column": f["name"]}
            if f["kind"] == "aggregation":
                spec["aggregation"] = f.get("agg", "sum")
        else:
            continue
        roles.setdefault(f["role"], []).append(spec)

    vis = {
        "type": v.get("type", "card"),
        "name": v.get("id") or uuid.uuid4().hex[:20],
        "x": v.get("x", 0),
        "y": v.get("y", 0),
        "width": v.get("width", 300),
        "height": v.get("height", 200),
        "config": {"roles": roles} if roles else {},
    }
    if vis["type"] == "textbox":
        vis["objects"] = _textbox_objects(v.get("text") or "")
    b.add_page("tmp", [vis])
    raw = b._build_layout()
    text = raw.decode("utf-16-le") if raw[1:2] == b"\x00" else raw.decode("utf-8")
    vc = json.loads(text)["sections"][0]["visualContainers"][0]
    vc["z"] = v.get("z", vc.get("z", 0))
    return vc


def new_pbir_visual(v: dict, schema_url: str | None = None) -> dict:
    query_state: dict[str, dict] = {}
    for f in v.get("fields", []):
        if f.get("kind") not in ("column", "measure", "aggregation"):
            continue
        proj = {
            "field": field_to_expr(f),
            "queryRef": query_ref(f),
            "nativeQueryRef": native_ref(f),
        }
        bucket = query_state.setdefault(f["role"], {"projections": []})
        if not bucket["projections"] and f["kind"] == "column":
            proj["active"] = True
        bucket["projections"].append(proj)

    visual: dict = {"visualType": v.get("type", "card")}
    if query_state:
        visual["query"] = {"queryState": query_state}
    if v.get("type") == "textbox":
        visual["objects"] = _textbox_objects(v.get("text") or "")
    if v.get("title"):
        visual["visualContainerObjects"] = {"title": title_objects(v["title"])}
    visual["drillFilterOtherVisuals"] = True

    return {
        "$schema": schema_url or PBIR_VISUAL_SCHEMA,
        "name": v.get("id") or uuid.uuid4().hex[:20],
        "position": {
            "x": v.get("x", 0),
            "y": v.get("y", 0),
            "z": v.get("z", 0),
            "height": v.get("height", 200),
            "width": v.get("width", 300),
            "tabOrder": v.get("z", 0),
        },
        "visual": visual,
    }
