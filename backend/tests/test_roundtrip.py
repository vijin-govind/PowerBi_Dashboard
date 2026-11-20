import copy
import io
import json
import zipfile

import pytest

from app import layout_legacy, layout_pbir
from app.model_info import Model
from app.pbix_io import open_pbix, write_pbix


def _edit(doc: dict) -> dict:
    """Move, retitle, delete, duplicate and add visuals; add a page."""
    doc = copy.deepcopy(doc)
    p0 = doc["pages"][0]
    chart = next(v for v in p0["visuals"] if v["id"] == "chart1")
    chart.update(x=111, y=222, width=333, height=244, title="Sales by Region")
    p0["visuals"] = [v for v in p0["visuals"] if v["id"] != "table1"]
    p0["visuals"].append(dict(chart, id="chart1copy", duplicateOf="chart1", x=500, y=400))
    p0["visuals"].append({
        "id": "newcard", "isNew": True, "type": "card", "x": 10, "y": 600, "z": 5000,
        "width": 200, "height": 100, "title": "Revenue",
        "fields": [{"role": "Values", "kind": "measure", "table": "Sales", "name": "Total Sales"}],
    })
    p0["name"] = "Summary"
    doc["pages"].append({"id": None, "name": "Blank", "width": 1280, "height": 720, "visuals": [
        {"id": "txt", "isNew": True, "type": "textbox", "x": 0, "y": 0, "z": 0, "width": 300, "height": 60, "text": "Hello", "fields": []},
    ]})
    return doc


def _check_package(out: bytes, original: bytes):
    zin, zout = zipfile.ZipFile(io.BytesIO(original)), zipfile.ZipFile(io.BytesIO(out))
    names = zout.namelist()
    assert "SecurityBindings" not in names
    assert "SecurityBindings" not in zout.read("[Content_Types].xml").decode()
    assert zout.read("DataModel") == zin.read("DataModel"), "DataModel must be byte-identical"
    assert zout.getinfo("DataModel").compress_type == zin.getinfo("DataModel").compress_type


def _check_doc(doc: dict):
    assert [p["name"] for p in doc["pages"]] == ["Summary", "Details", "Blank"]
    vis = {v["id"]: v for v in doc["pages"][0]["visuals"]}
    assert "table1" not in vis
    c = vis["chart1"]
    assert (c["x"], c["y"], c["width"], c["height"]) == (111, 222, 333, 244)
    assert c["title"] == "Sales by Region"
    assert vis["chart1copy"]["x"] == 500 and vis["chart1copy"]["type"] == "clusteredColumnChart"
    assert vis["chart1copy"]["fields"] == c["fields"]
    card = vis["newcard"]
    assert card["type"] == "card" and card["title"] == "Revenue"
    assert card["fields"][0]["name"] == "Total Sales" and card["fields"][0]["kind"] == "measure"
    txt = doc["pages"][2]["visuals"][0]
    assert txt["type"] == "textbox" and txt["text"] == "Hello"


def test_legacy_parse(legacy_pbix):
    doc = layout_legacy.parse(open_pbix(legacy_pbix))
    assert doc["format"] == "legacy"
    assert [p["name"] for p in doc["pages"]] == ["Overview", "Details"]
    chart = next(v for v in doc["pages"][0]["visuals"] if v["id"] == "chart1")
    assert chart["type"] == "clusteredColumnChart"
    assert {(f["role"], f["name"]) for f in chart["fields"]} == {("Category", "Region"), ("Y", "Total Sales")}


def test_legacy_roundtrip(legacy_pbix):
    pkg = open_pbix(legacy_pbix)
    model = Model(legacy_pbix)
    doc = _edit(layout_legacy.parse(pkg))
    out = write_pbix(pkg, layout_legacy.apply(pkg, doc, model.schema))
    _check_package(out, legacy_pbix)
    raw = zipfile.ZipFile(io.BytesIO(out)).read("Report/Layout")
    assert raw[1:2] == b"\x00", "Layout must stay UTF-16 LE"
    _check_doc(layout_legacy.parse(open_pbix(out)))
    # The file still opens as a model for PBIXRay.
    assert Model(out).schema["tables"][0]["name"] == "Sales"


def test_pbir_roundtrip(pbir_pbix):
    pkg = open_pbix(pbir_pbix)
    assert pkg.report_format == "pbir"
    model = Model(pbir_pbix)
    doc = layout_pbir.parse(pkg)
    assert [p["name"] for p in doc["pages"]] == ["Overview", "Details"]
    edited = _edit(doc)
    replace, removed = layout_pbir.apply(pkg, edited, model.schema)
    out = write_pbix(pkg, replace, removed)
    _check_package(out, pbir_pbix)
    names = zipfile.ZipFile(io.BytesIO(out)).namelist()
    assert not any("/visuals/table1/" in n for n in names), "deleted visual folder (incl. mobile.json) removed"
    _check_doc(layout_pbir.parse(open_pbix(out)))
    meta = json.loads(zipfile.ZipFile(io.BytesIO(out)).read("Report/definition/pages/pages.json"))
    assert len(meta["pageOrder"]) == 3


def test_pbir_new_visual_has_schema(pbir_pbix):
    pkg = open_pbix(pbir_pbix)
    edited = _edit(layout_pbir.parse(pkg))
    replace, _ = layout_pbir.apply(pkg, edited, Model(pbir_pbix).schema)
    path = next(k for k in replace if k.endswith("/visuals/newcard/visual.json"))
    vj = json.loads(replace[path])
    assert vj["$schema"].endswith("visualContainer/2.1.0/schema.json"), "reuses the file's schema version"
    proj = vj["visual"]["query"]["queryState"]["Values"]["projections"][0]
    assert proj["field"] == {"Measure": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": "Total Sales"}}


@pytest.mark.parametrize("fixture", ["legacy_pbix"])
def test_preview(fixture, request):
    m = Model(request.getfixturevalue(fixture))
    data = m.preview([
        {"role": "Category", "kind": "column", "table": "Sales", "name": "Region"},
        {"role": "Y", "kind": "measure", "table": "Sales", "name": "Total Sales"},
    ])
    got = dict(zip(data["categories"], data["series"][0]["values"]))
    assert got == {"East": 1500, "North": 2000.5, "South": 1350, "West": 700}
    card = m.preview([{"role": "Values", "kind": "measure", "table": "Sales", "name": "Avg Price"}])
    assert card["value"] == pytest.approx(5550.5 / 44)
    table = m.preview([{"role": "Values", "kind": "column", "table": "Sales", "name": "Product"}])
    assert sorted(r[0] for r in table["rows"]) == ["Gadget", "Gizmo", "Widget"]
