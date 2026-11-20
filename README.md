# PBIX Canvas

A web app that opens a Power BI Desktop file (`.pbix`), lets you edit the
report layout on a Figma-like canvas, and exports it back to `.pbix`.

**Status: proof of concept.** The upload → edit → export round trip works and
is covered by automated tests. Exported files have **not yet been opened in
Power BI Desktop** (that needs Windows). Do that before relying on it.

## What you can do

- Open `.pbix` files in both report formats: the legacy `Report/Layout` and
  the newer **PBIR** (`Report/definition/…`), which became Desktop's default
  in 2026.
- Drag, resize (8 px snap grid), nudge with the arrow keys, change the stacking
  order, duplicate and delete visuals.
- Edit visual titles, and add, rename, reorder, resize and delete pages.
- Insert new visuals (card, column, bar, line, pie, table, slicer, text box) and
  bind them by dragging fields from the field list. Drop a field on an empty
  part of the canvas to create a visual for it automatically.
- Charts preview with **real data** from the file's model where possible.
  Simple measures such as SUM, AVERAGE, COUNTROWS and DIVIDE are evaluated
  approximately; other visuals show "sample data".
- Undo/redo, zoom, and fit to screen.
- Export `.pbix`.

## How export works (and why it's safe)

| Part of the .pbix | What we do |
|---|---|
| `DataModel` (tables, data, measures) | Copied **byte for byte** and never re-encoded |
| `Report/Layout` (legacy) | Rewritten as UTF-16 LE JSON, keeping all unknown properties of existing visuals |
| `Report/definition/**` (PBIR) | Changed `page.json`/`visual.json` files rewritten; deleted pages/visuals removed |
| `SecurityBindings` | Removed (Desktop recreates it; a stale copy makes Desktop say the file is corrupted). You may need to re-enter data source credentials on first refresh |
| `[Content_Types].xml` | Kept consistent with the removed/added parts |

New legacy-format visuals are generated with
[pbix-mcp](https://pypi.org/project/pbix-mcp/)'s binding compiler. New PBIR
visuals follow Microsoft's published `visualContainer` JSON schema, reusing
the schema version already in the file. The model is read with
[PBIXRay](https://github.com/hugoberry/pbixray).

Uploaded files are held **in memory only**, for at most one hour per session.

## Run it

Requires Python 3.10+.

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

Then open http://localhost:8000.

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
```

The tests build synthetic `.pbix` files (legacy and PBIR) with pbix-mcp and
check that each edit (move, retitle, delete, duplicate, add visual, add page)
comes through the round trip, and that the `DataModel` stays byte-identical.

## Project layout

```
backend/app/
  main.py            FastAPI routes: upload, preview, export
  pbix_io.py         ZIP container read/write, SecurityBindings, content types
  layout_legacy.py   Report/Layout parse + apply edits
  layout_pbir.py     PBIR parse + apply edits
  visual_factory.py  create new visuals (both formats)
  fields.py          query-field <-> editor field conversions
  model_info.py      PBIXRay field list + approximate chart previews
frontend/            static editor (vanilla JS, ECharts, interact.js)
```

## Known limitations

- Field bindings of **existing** visuals are read-only. They're preserved
  exactly, but you can only bind fields on new visuals.
- Existing text boxes can be moved but not re-edited.
- Moving a group doesn't move its children.
- Custom/marketplace visuals and other unsupported types are drawn as labelled
  placeholders. Desktop renders them normally after export.
- Previews are approximate: no full DAX engine, and no filters or slicer
  interactions.
- DirectQuery or live-connection files: layout editing works, but there's no
  data preview.

## Next steps

1. Open exported files in Power BI Desktop across versions, using real
   Desktop-saved files.
2. Edit bindings and formatting (colors, fonts) of existing visuals.
3. Multi-select, alignment guides, theme editor.
4. Optional Microsoft sign-in to run exact DAX through the Power BI REST API.
5. PBIP/TMDL export for editing the data model.
