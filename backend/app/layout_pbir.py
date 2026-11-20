"""PBIR (enhanced report format) stored inside a .pbix under
``Report/definition/``. Publicly documented JSON with schemas:

    Report/definition/pages/pages.json                     page order
    Report/definition/pages/<page>/page.json               page settings
    Report/definition/pages/<page>/visuals/<v>/visual.json visual container
"""

from __future__ import annotations

import copy
import json
import posixpath
import re
import uuid

from .fields import expr_to_field, read_title, title_changed, title_objects
from .pbix_io import PBIR_PREFIX, PbixPackage
from .visual_factory import new_pbir_visual

PAGES_DIR = PBIR_PREFIX + "pages/"
PAGES_JSON = PAGES_DIR + "pages.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json"
PAGES_SCHEMA = (
    "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json"
)

_PAGE_RE = re.compile(r"^Report/definition/pages/([^/]+)/page\.json$")
_VISUAL_RE = re.compile(r"^Report/definition/pages/([^/]+)/visuals/([^/]+)/visual\.json$")


def _json(data: bytes) -> dict:
    return json.loads(data.decode("utf-8-sig"))


def _dump(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


def _index(pkg: PbixPackage):
    pages: dict[str, dict] = {}
    visuals: dict[str, dict[str, tuple[str, dict]]] = {}
    for name, data in pkg.entries.items():
        m = _PAGE_RE.match(name)
        if m:
            pages[m.group(1)] = _json(data)
            continue
        m = _VISUAL_RE.match(name)
        if m:
            visuals.setdefault(m.group(1), {})[m.group(2)] = (name, _json(data))
    meta = _json(pkg.entries[PAGES_JSON]) if PAGES_JSON in pkg.entries else {}
    order = [p for p in meta.get("pageOrder", []) if p in pages]
    order += sorted(p for p in pages if p not in order)
    return meta, order, pages, visuals


def _visual_to_editor(folder: str, vj: dict) -> dict:
    pos = vj.get("position", {})
    vis = vj.get("visual") or {}
    fields = []
    for role, bucket in ((vis.get("query") or {}).get("queryState") or {}).items():
        for proj in bucket.get("projections", []):
            f = expr_to_field(proj.get("field", {}))
            f["role"] = role
            fields.append(f)
    if "visualGroup" in vj:
        vtype, title = "group", vj["visualGroup"].get("displayName")
    else:
        vtype, title = vis.get("visualType", "unknown"), read_title(vis.get("visualContainerObjects"))
    text = None
    if vtype == "textbox":
        try:
            paras = vis["objects"]["general"][0]["properties"]["paragraphs"]
            text = "\n".join("".join(r.get("value", "") for r in p.get("textRuns", [])) for p in paras)
        except (KeyError, IndexError, TypeError):
            pass
    return {
        "id": vj.get("name", folder),
        "folder": folder,
        "type": vtype,
        "x": pos.get("x", 0),
        "y": pos.get("y", 0),
        "z": pos.get("z", 0),
        "width": pos.get("width", 100),
        "height": pos.get("height", 100),
        "title": title,
        "text": text,
        "parent": vj.get("parentGroupName"),
        "fields": fields,
    }


def parse(pkg: PbixPackage) -> dict:
    _, order, pages, visuals = _index(pkg)
    out = []
    for pid in order:
        pj = pages[pid]
        out.append(
            {
                "id": pid,
                "name": pj.get("displayName", pid),
                "width": pj.get("width", 1280),
                "height": pj.get("height", 720),
                "visuals": [_visual_to_editor(f, vj) for f, (_, vj) in visuals.get(pid, {}).items()],
            }
        )
    return {"format": "pbir", "pages": out}


def apply(pkg: PbixPackage, edited: dict, schema: dict) -> tuple[dict[str, bytes], set[str]]:
    """Return (replaced/added parts, removed parts)."""
    meta, _, pages, visuals = _index(pkg)
    all_visuals = {
        vj.get("name", folder): (pid, folder, path, vj)
        for pid, vs in visuals.items()
        for folder, (path, vj) in vs.items()
    }
    any_schema = next((vj.get("$schema") for *_, vj in all_visuals.values() if vj.get("$schema")), None)
    page_schema = next((p.get("$schema") for p in pages.values() if p.get("$schema")), PAGE_SCHEMA)

    replace: dict[str, bytes] = {}
    keep: set[str] = set()
    order: list[str] = []

    for page in edited.get("pages", []):
        pid = page.get("id")
        if pid in pages:
            pj = copy.deepcopy(pages[pid])
        else:
            pid = uuid.uuid4().hex[:20]
            pj = {"$schema": page_schema, "name": pid, "displayOption": "FitToPage"}
        pj["displayName"] = page.get("name", pj.get("displayName", pid))
        pj["width"] = page.get("width", pj.get("width", 1280))
        pj["height"] = page.get("height", pj.get("height", 720))
        page_path = f"{PAGES_DIR}{pid}/page.json"
        replace[page_path] = _dump(pj)
        keep.add(page_path)
        order.append(pid)

        for v in page.get("visuals", []):
            src = None
            if v.get("id") in all_visuals and not v.get("isNew"):
                src = all_visuals[v["id"]]
            elif v.get("duplicateOf") in all_visuals:
                src = all_visuals[v["duplicateOf"]]
            if src is not None:
                _, _, _, vj = src
                vj = copy.deepcopy(vj)
                before = _visual_to_editor(vj.get("name", ""), vj)
            else:
                vj = new_pbir_visual(v, any_schema)
                before = {"title": v.get("title")}
            vid = v.get("id") or vj.get("name") or uuid.uuid4().hex[:20]
            vj["name"] = vid
            pos = vj.setdefault("position", {})
            for k in ("x", "y", "z", "width", "height"):
                if k in v:
                    pos[k] = v[k]
            if title_changed(v.get("title"), before.get("title")):
                if "visualGroup" in vj:
                    vj["visualGroup"]["displayName"] = v["title"]
                else:
                    vco = vj.setdefault("visual", {}).setdefault("visualContainerObjects", {})
                    if vco.get("title"):
                        vco["title"][0].setdefault("properties", {}).update(title_objects(v["title"])[0]["properties"])
                    else:
                        vco["title"] = title_objects(v["title"])
            vpath = f"{PAGES_DIR}{pid}/visuals/{vid}/visual.json"
            replace[vpath] = _dump(vj)
            keep.add(vpath)

    meta = dict(meta) or {"$schema": PAGES_SCHEMA}
    meta["pageOrder"] = order
    if meta.get("activePageName") not in order and order:
        meta["activePageName"] = order[0]
    replace[PAGES_JSON] = _dump(meta)
    keep.add(PAGES_JSON)

    # Drop page/visual parts (and their sibling files, e.g. mobile.json) that
    # belong to deleted pages or visuals.
    kept_page_dirs = {f"{PAGES_DIR}{p}/" for p in order}
    kept_visual_dirs = {posixpath.dirname(p) + "/" for p in keep if p.endswith("/visual.json")}
    removed = set()
    for name in pkg.entries:
        if not name.startswith(PAGES_DIR) or name == PAGES_JSON:
            continue
        page_dir = PAGES_DIR + name[len(PAGES_DIR):].split("/", 1)[0] + "/"
        if page_dir not in kept_page_dirs:
            removed.add(name)
            continue
        if "/visuals/" in name:
            vdir = name.split("/visuals/", 1)[0] + "/visuals/" + name.split("/visuals/", 1)[1].split("/", 1)[0] + "/"
            if vdir not in kept_visual_dirs:
                removed.add(name)
    return replace, removed
