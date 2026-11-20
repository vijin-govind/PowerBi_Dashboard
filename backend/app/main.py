"""FastAPI app: upload a .pbix, edit its report layout, export a .pbix."""

from __future__ import annotations

import mimetypes
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import layout_legacy, layout_pbir
from .model_info import Model
from .pbix_io import PbixError, PbixPackage, open_pbix, write_pbix

# Some Windows registries map .js to text/plain, which breaks the page.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")

MAX_UPLOAD = 500 * 1024 * 1024
SESSION_TTL = 60 * 60  # uploaded files live in memory only, for one hour

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="PBIX Canvas", version="0.1.0")


@dataclass
class Session:
    filename: str
    pkg: PbixPackage
    model: Model
    doc: dict
    touched: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


_sessions: dict[str, Session] = {}
_lock = threading.Lock()


def _gc() -> None:
    now = time.time()
    with _lock:
        for sid in [s for s, v in _sessions.items() if now - v.touched > SESSION_TTL]:
            del _sessions[sid]


def _get(sid: str) -> Session:
    _gc()
    with _lock:
        s = _sessions.get(sid)
    if s is None:
        raise HTTPException(404, "Session expired. Please upload the file again.")
    s.touched = time.time()
    return s


class ExportBody(BaseModel):
    pages: list[dict]


class PreviewBody(BaseModel):
    fields: list[dict]


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 500 MB).")
    if not (file.filename or "").lower().endswith(".pbix"):
        raise HTTPException(400, "Please upload a .pbix file.")
    try:
        pkg = open_pbix(data)
        fmt = pkg.report_format
        doc = layout_pbir.parse(pkg) if fmt == "pbir" else layout_legacy.parse(pkg)
    except PbixError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Could not read the report layout: {exc}") from exc
    model = Model(data)
    sid = uuid.uuid4().hex
    with _lock:
        _sessions[sid] = Session(file.filename or "report.pbix", pkg, model, doc)
    return {
        "session": sid,
        "filename": file.filename,
        "format": fmt,
        "report": doc,
        "model": model.schema,
        "modelError": model.error,
        "hasSecurityBindings": "SecurityBindings" in pkg.entries,
    }


@app.post("/api/session/{sid}/preview")
def preview(sid: str, body: PreviewBody):
    s = _get(sid)
    try:
        with s.lock:  # PBIXRay is not guaranteed thread-safe
            return {"data": s.model.preview(body.fields)}
    except Exception as exc:  # preview is best-effort
        return {"data": None, "error": str(exc)}


def _build(s: Session, pages: list[dict]) -> bytes:
    edited = {"pages": pages}
    if s.pkg.report_format == "pbir":
        replace, removed = layout_pbir.apply(s.pkg, edited, s.model.schema)
    else:
        replace, removed = layout_legacy.apply(s.pkg, edited, s.model.schema), set()
    return write_pbix(s.pkg, replace, removed)


@app.post("/api/session/{sid}/export")
def export(sid: str, body: ExportBody):
    s = _get(sid)
    try:
        data = _build(s, body.pages)
    except Exception as exc:
        raise HTTPException(500, f"Export failed: {exc}") from exc
    stem = re.sub(r"[^\w\- .]", "_", Path(s.filename).stem) or "report"
    return Response(
        data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{stem}-edited.pbix"'},
    )


@app.delete("/api/session/{sid}")
def close(sid: str):
    with _lock:
        _sessions.pop(sid, None)
    return {"ok": True}


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/", StaticFiles(directory=FRONTEND), name="static")
