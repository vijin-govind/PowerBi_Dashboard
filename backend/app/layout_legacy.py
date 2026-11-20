"""Legacy report format: a single UTF-16 LE JSON part at ``Report/Layout``.

Nested JSON strings (``config``, ``filters``, ``query``...) are decoded only
where we need them and re-encoded on write, everything else is kept as-is.
"""

from __future__ import annotations

import copy
import json
import uuid

from .fields import expr_to_field, read_title, title_changed, title_objects
from .pbix_io import LEGACY_LAYOUT, PbixPackage, decode_layout, encode_layout
from .visual_factory import new_legacy_container


def _loads(value, default):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value if value is not None else default


def _visual_from_container(vc: dict) -> dict:
    cfg = _loads(vc.get("config"), {})
    sv = cfg.get("singleVisual") or {}
    if "singleVisualGroup" in cfg:
        vtype = "group"
        title = cfg["singleVisualGroup"].get("displayName")
    else:
        vtype = sv.get("visualType", "unknown")
        title = read_title(sv.get("vcObjects"))

    fields: list[dict] = []
    proto = sv.get("prototypeQuery") or {}
    aliases = {f.get("Name"): f.get("Entity") for f in proto.get("From", [])}
    by_ref = {s.get("Name"): s for s in proto.get("Select", [])}
    for role, items in (sv.get("projections") or {}).items():
        for item in items:
            sel = by_ref.get(item.get("queryRef"))
            if sel is None:
                continue
            f = expr_to_field(sel, aliases)
            f["role"] = role
            fields.append(f)

    text = None
    if vtype == "textbox":
        try:
            paras = sv["objects"]["general"][0]["properties"]["paragraphs"]
            text = "\n".join("".join(r.get("value", "") for r in p.get("textRuns", [])) for p in paras)
        except (KeyError, IndexError, TypeError):
            text = None

    return {
        "id": cfg.get("name") or uuid.uuid4().hex[:20],
        "type": vtype,
        "x": vc.get("x", 0),
        "y": vc.get("y", 0),
        "z": vc.get("z", 0),
        "width": vc.get("width", 100),
        "height": vc.get("height", 100),
        "title": title,
        "text": text,
        "parent": cfg.get("parentGroupName"),
        "fields": fields,
    }


def parse(pkg: PbixPackage) -> dict:
    layout, _ = decode_layout(pkg.entries[LEGACY_LAYOUT])
    doc = json.loads(layout)
    sections = sorted(doc.get("sections", []), key=lambda s: s.get("ordinal", 0))
    pages = []
    for s in sections:
        pages.append(
            {
                "id": s.get("name"),
                "name": s.get("displayName", s.get("name")),
                "width": s.get("width", 1280),
                "height": s.get("height", 720),
                "visuals": [_visual_from_container(vc) for vc in s.get("visualContainers", [])],
            }
        )
    return {"format": "legacy", "pages": pages}


def _set_position(vc: dict, cfg: dict, v: dict) -> None:
    for k in ("x", "y", "z", "width", "height"):
        if k in v:
            vc[k] = v[k]
    for lay in cfg.get("layouts", []) or []:
        pos = lay.setdefault("position", {})
        for k in ("x", "y", "z", "width", "height"):
            if k in v:
                pos[k] = v[k]


def _set_title(cfg: dict, title: str | None) -> None:
    if title is None:
        return
    if "singleVisualGroup" in cfg:
        cfg["singleVisualGroup"]["displayName"] = title
        return
    sv = cfg.setdefault("singleVisual", {})
    vco = sv.setdefault("vcObjects", {})
    existing = vco.get("title")
    if existing:
        props = existing[0].setdefault("properties", {})
        props.update(title_objects(title)[0]["properties"])
    else:
        vco["title"] = title_objects(title)


def apply(pkg: PbixPackage, edited: dict, schema: dict) -> dict[str, bytes]:
    """Return the replaced parts for an edited document."""
    text, had_bom = decode_layout(pkg.entries[LEGACY_LAYOUT])
    doc = json.loads(text)
    orig_sections = {s.get("name"): s for s in doc.get("sections", [])}
    orig_visuals: dict[str, tuple[dict, dict]] = {}
    for s in doc.get("sections", []):
        for vc in s.get("visualContainers", []):
            v = _visual_from_container(vc)
            orig_visuals[v["id"]] = (vc, v)

    new_sections = []
    for ordinal, page in enumerate(edited.get("pages", [])):
        sec = orig_sections.get(page.get("id"))
        if sec is None:
            sec = {
                "name": "ReportSection" + uuid.uuid4().hex[:20],
                "displayName": page.get("name", f"Page {ordinal + 1}"),
                "filters": "[]",
                "config": "{}",
                "displayOption": 1,
                "visualContainers": [],
            }
        sec["displayName"] = page.get("name", sec.get("displayName"))
        sec["width"] = page.get("width", sec.get("width", 1280))
        sec["height"] = page.get("height", sec.get("height", 720))
        sec["ordinal"] = ordinal

        containers = []
        for v in page.get("visuals", []):
            if v.get("id") in orig_visuals and not v.get("isNew"):
                vc, before = orig_visuals[v["id"]]
            elif v.get("duplicateOf") in orig_visuals:
                vc = copy.deepcopy(orig_visuals[v["duplicateOf"]][0])
                before = orig_visuals[v["duplicateOf"]][1]
                vc.pop("id", None)
            else:
                vc = new_legacy_container(v, schema)
                before = {"title": None}
            cfg = _loads(vc.get("config"), {})
            cfg["name"] = v.get("id") or cfg.get("name")
            _set_position(vc, cfg, v)
            if title_changed(v.get("title"), before.get("title")):
                _set_title(cfg, v["title"])
            vc["config"] = json.dumps(cfg, ensure_ascii=False)
            containers.append(vc)
        sec["visualContainers"] = containers
        new_sections.append(sec)

    doc["sections"] = new_sections
    out = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    return {LEGACY_LAYOUT: encode_layout(out, had_bom)}
