"""Low-level reading and writing of the .pbix ZIP container.

A .pbix is an OPC/ZIP package. We never touch the binary ``DataModel``: it is
copied byte-for-byte. Only the report part is replaced, ``SecurityBindings``
is dropped (Desktop recreates it; keeping a stale one makes Desktop report the
file as corrupted) and ``[Content_Types].xml`` is kept consistent.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

LEGACY_LAYOUT = "Report/Layout"
PBIR_PREFIX = "Report/definition/"
SECURITY_BINDINGS = "SecurityBindings"
CONTENT_TYPES = "[Content_Types].xml"

UTF16_BOM = b"\xff\xfe"


class PbixError(ValueError):
    """The upload is not a .pbix we can work with."""


@dataclass
class PbixPackage:
    """An opened .pbix kept in memory: entry order, bytes and compression."""

    entries: dict[str, bytes]
    compress_types: dict[str, int]
    order: list[str] = field(default_factory=list)

    @property
    def report_format(self) -> str:
        if any(n.startswith(PBIR_PREFIX) for n in self.entries):
            return "pbir"
        if LEGACY_LAYOUT in self.entries:
            return "legacy"
        raise PbixError(
            "No report found in this file (neither Report/Layout nor "
            "Report/definition/). Live-connection-only or corrupted file?"
        )


def open_pbix(data: bytes) -> PbixPackage:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PbixError("Not a .pbix file (it is not a ZIP package).") from exc
    entries: dict[str, bytes] = {}
    ctypes: dict[str, int] = {}
    order: list[str] = []
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            entries[info.filename] = zf.read(info)
            ctypes[info.filename] = info.compress_type
            order.append(info.filename)
    pkg = PbixPackage(entries, ctypes, order)
    pkg.report_format  # validate early
    return pkg


def decode_layout(raw: bytes) -> tuple[str, bool]:
    """Decode the legacy Layout part (UTF-16 LE). Returns (text, had_bom)."""
    had_bom = raw.startswith(UTF16_BOM)
    return raw.decode("utf-16-le").lstrip("﻿"), had_bom


def encode_layout(text: str, with_bom: bool) -> bytes:
    data = text.encode("utf-16-le")
    return UTF16_BOM + data if with_bom else data


def _clean_content_types(xml: str, removed: set[str], need_json_default: bool) -> str:
    for name in removed:
        part = re.escape("/" + name)
        xml = re.sub(rf'<Override\s+PartName="{part}"[^>]*/>', "", xml)
    if need_json_default and 'Extension="json"' not in xml:
        xml = xml.replace(
            "</Types>",
            '<Default Extension="json" ContentType="" /></Types>',
        )
    return xml


def write_pbix(
    pkg: PbixPackage,
    replace: dict[str, bytes],
    remove: set[str] | None = None,
) -> bytes:
    """Write a new package.

    ``replace`` maps entry name -> new bytes (new names are appended after the
    existing ones); ``remove`` lists entries to drop. ``SecurityBindings`` is
    always dropped.
    """
    remove = set(remove or ()) | {SECURITY_BINDINGS}
    names = [n for n in pkg.order if n not in remove]
    names += [n for n in replace if n not in pkg.entries and n not in remove]
    removed_existing = {n for n in remove if n in pkg.entries}
    added_json = any(n.endswith(".json") and n not in pkg.entries for n in replace)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name in names:
            data = replace.get(name, pkg.entries.get(name))
            if name == CONTENT_TYPES:
                data = _clean_content_types(
                    data.decode("utf-8-sig"), removed_existing, added_json
                ).encode("utf-8")
            ctype = pkg.compress_types.get(name, zipfile.ZIP_DEFLATED)
            zf.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), data, ctype)
    return out.getvalue()
