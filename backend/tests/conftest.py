"""Test fixtures: synthetic .pbix files built with pbix-mcp (no Desktop)."""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def build_legacy_pbix() -> bytes:
    from pbix_mcp.builder import PBIXBuilder

    b = PBIXBuilder("SalesModel")
    rows = [
        {"Region": r, "Product": p, "Amount": a, "Qty": q}
        for r, p, a, q in [
            ("North", "Widget", 1200.5, 10), ("North", "Gadget", 800, 6),
            ("South", "Widget", 950, 8), ("South", "Gizmo", 400, 3),
            ("East", "Gadget", 1500, 12), ("West", "Gizmo", 700, 5),
        ]
    ]
    b.add_table("Sales", [
        {"name": "Region", "data_type": "String"}, {"name": "Product", "data_type": "String"},
        {"name": "Amount", "data_type": "Double"}, {"name": "Qty", "data_type": "Int64"},
    ], rows=rows)
    b.add_measure("Sales", "Total Sales", "SUM(Sales[Amount])")
    b.add_measure("Sales", "Avg Price", "DIVIDE([Total Sales], SUM(Sales[Qty]))")
    b.add_page("Overview", [
        {"type": "card", "name": "card1", "config": {"measure": "Total Sales"}, "x": 20, "y": 20, "width": 250, "height": 120},
        {"type": "clusteredColumnChart", "name": "chart1", "config": {"category": {"table": "Sales", "column": "Region"}, "measure": "Total Sales"}, "x": 300, "y": 20, "width": 600, "height": 350},
        {"type": "tableEx", "name": "table1", "config": {"columns": [{"table": "Sales", "column": "Product"}, {"table": "Sales", "column": "Amount"}]}, "x": 20, "y": 400, "width": 880, "height": 280},
    ])
    b.add_page("Details", [
        {"type": "slicer", "name": "slicer1", "config": {"column": {"table": "Sales", "column": "Region"}}, "x": 20, "y": 20, "width": 200, "height": 300},
    ])
    data = b.build()
    # Add a fake SecurityBindings part like a Desktop-saved file has.
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in src.infolist():
            body = src.read(info)
            if info.filename == "[Content_Types].xml":
                body = body.replace(b"</Types>", b'<Override PartName="/SecurityBindings" ContentType="" /></Types>')
            zf.writestr(info, body)
        zf.writestr("SecurityBindings", b"\x01\x02encrypted")
    return out.getvalue()


def legacy_to_pbir(data: bytes) -> bytes:
    """Re-shape a legacy file into a PBIR-in-pbix file (Report/definition)."""
    from app.fields import field_to_expr, native_ref, query_ref
    from app.layout_legacy import parse
    from app.pbix_io import open_pbix

    doc = parse(open_pbix(data))
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    pre = "Report/definition/"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for info in src.infolist():
            if info.filename == "Report/Layout":
                continue
            zf.writestr(info, src.read(info))
        zf.writestr(pre + "version.json", json.dumps({"version": "2.0.0"}))
        zf.writestr(pre + "report.json", json.dumps({"themeCollection": {}}))
        zf.writestr(pre + "pages/pages.json", json.dumps({"pageOrder": [p["id"] for p in doc["pages"]], "activePageName": doc["pages"][0]["id"]}))
        for p in doc["pages"]:
            zf.writestr(f"{pre}pages/{p['id']}/page.json", json.dumps({"name": p["id"], "displayName": p["name"], "width": p["width"], "height": p["height"], "displayOption": "FitToPage"}))
            for v in p["visuals"]:
                qs = {}
                for f in v["fields"]:
                    qs.setdefault(f["role"], {"projections": []})["projections"].append(
                        {"field": field_to_expr(f), "queryRef": query_ref(f), "nativeQueryRef": native_ref(f)})
                vj = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.1.0/schema.json",
                      "name": v["id"], "position": {k: v[k] for k in ("x", "y", "z", "width", "height")},
                      "visual": {"visualType": v["type"], "query": {"queryState": qs}}}
                zf.writestr(f"{pre}pages/{p['id']}/visuals/{v['id']}/visual.json", json.dumps(vj))
                zf.writestr(f"{pre}pages/{p['id']}/visuals/{v['id']}/mobile.json", "{}")
    return out.getvalue()


@pytest.fixture(scope="session")
def legacy_pbix() -> bytes:
    return build_legacy_pbix()


@pytest.fixture(scope="session")
def pbir_pbix(legacy_pbix) -> bytes:
    return legacy_to_pbir(legacy_pbix)
