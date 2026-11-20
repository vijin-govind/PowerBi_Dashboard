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

You need **Python 3.10 or newer**.

### Windows (easiest)

1. Install Python from https://www.python.org/downloads/windows/ and tick
   **"Add python.exe to PATH"** in the installer.
2. Download this repository (Code → Download ZIP) and unzip it.
3. Double-click **`run.bat`**.

The first run creates a `.venv` folder and installs the packages, which takes
about a minute. Your browser then opens PBIX Canvas. Keep the black window open
while you use the app, and close it to stop.

<details><summary>Manual Windows setup (PowerShell)</summary>

Run these from the repository folder (the one that contains `run.py`), one
line at a time:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe run.py
```

This calls the venv's Python directly, so you don't need `Activate.ps1` or
any change to PowerShell's execution policy.
</details>

### macOS / Linux

```bash
./run.sh
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| `'python' is not recognized` / the Microsoft Store opens | Install Python from python.org with "Add to PATH" ticked, or use `py -3` |
| `Activate.ps1 cannot be loaded … running scripts is disabled` | Not needed. Use `run.bat` or the manual commands above |
| `ModuleNotFoundError: No module named 'app'` | Start with `run.py` from the repository folder, not `uvicorn` from another folder |
| `pip install` fails behind a company network | Set `HTTPS_PROXY`, or ask IT to allow `pypi.org` and `files.pythonhosted.org` |
| Port 8000 already in use | `run.py` automatically picks the next free port (8001, 8002, …) |
| Blank page | Press Ctrl+F5. If it's still blank, send the text in the black window |

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
