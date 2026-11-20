"""Read the semantic model (field list + data) with PBIXRay and compute
approximate preview data for the editor's charts.

Preview numbers are an approximation: simple measures (SUM, AVERAGE, MIN,
MAX, COUNT, COUNTROWS, DISTINCTCOUNT, and arithmetic between such measures)
are evaluated with pandas. Anything else returns ``None`` and the editor
falls back to placeholder data. The real numbers are always computed by Power
BI Desktop after export.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile

log = logging.getLogger(__name__)

MAX_ROWS = 200_000
MAX_CATEGORIES = 50


class Model:
    def __init__(self, data: bytes):
        self.schema: dict = {"tables": []}
        self._ray = None
        self._frames: dict = {}
        self.error: str | None = None
        self._measures: dict[str, str] = {}
        try:
            from pbixray import PBIXRay

            # PBIXRay needs a path; use a private temp file removed right away
            # after parsing (the model is then held in memory only).
            fd, path = tempfile.mkstemp(suffix=".pbix")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                self._ray = PBIXRay(path)
                self._build_schema()
                self._load_frames()
            finally:
                os.unlink(path)
        except Exception as exc:  # model unreadable (DirectQuery, live, etc.)
            log.warning("model read failed: %s", exc)
            self.error = f"Could not read the data model: {exc}"
            self._ray = None

    def _build_schema(self) -> None:
        ray = self._ray
        sch = ray.schema
        try:
            meas = ray.dax_measures
        except Exception:
            meas = None
        tables = []
        for t in list(ray.tables):
            if str(t).startswith(("LocalDateTable_", "DateTableTemplate_")):
                continue
            cols = sch[sch["TableName"] == t]
            columns = [
                {"name": r.ColumnName, "dataType": str(r.PandasDataType)}
                for r in cols.itertuples()
                if not str(r.ColumnName).startswith("RowNumber")
            ]
            measures = []
            if meas is not None and len(meas):
                for r in meas[meas["TableName"] == t].itertuples():
                    measures.append({"name": r.Name, "expression": r.Expression})
                    self._measures[r.Name] = r.Expression or ""
            tables.append({"name": str(t), "columns": columns, "measures": measures})
        self.schema = {"tables": tables}

    def _load_frames(self) -> None:
        for t in self.schema["tables"]:
            try:
                df = self._ray.get_table(t["name"])
                self._frames[t["name"]] = df.head(MAX_ROWS)
            except Exception as exc:
                log.info("table %s not loaded: %s", t["name"], exc)

    # ------------------------------------------------------------------
    # Preview evaluation
    # ------------------------------------------------------------------

    _AGG = re.compile(
        r"^\s*(SUM|AVERAGE|MIN|MAX|COUNT|COUNTA|DISTINCTCOUNT)\s*\(\s*'?([^'\[\]]+?)'?\s*\[([^\]]+)\]\s*\)\s*$",
        re.I,
    )
    _COUNTROWS = re.compile(r"^\s*COUNTROWS\s*\(\s*'?([^'\(\)]+?)'?\s*\)\s*$", re.I)
    _DIVIDE = re.compile(r"^\s*DIVIDE\s*\((.+),(.+)\)\s*$", re.I | re.S)

    def _agg(self, func: str, series):
        func = func.lower()
        if func == "sum":
            return series.sum()
        if func == "average":
            return series.mean()
        if func == "min":
            return series.min()
        if func == "max":
            return series.max()
        if func in ("count", "counta", "countnonnull"):
            return series.count()
        if func == "distinctcount":
            return series.nunique()
        if func == "median":
            return series.median()
        return None

    def _eval_expr(self, expr: str, df_by_table: dict, depth: int = 0):
        """Evaluate a tiny DAX subset against already-filtered frames."""
        if depth > 6:
            return None
        expr = expr.strip()
        m = self._AGG.match(expr)
        if m:
            df = df_by_table.get(m.group(2))
            if df is None or m.group(3) not in df:
                return None
            return self._agg(m.group(1), df[m.group(3)])
        m = self._COUNTROWS.match(expr)
        if m:
            df = df_by_table.get(m.group(1))
            return None if df is None else len(df)
        m = self._DIVIDE.match(expr)
        if m:
            a = self._eval_expr(m.group(1), df_by_table, depth + 1)
            b = self._eval_expr(m.group(2), df_by_table, depth + 1)
            return None if a is None or not b else a / b
        mm = re.fullmatch(r"\s*\[([^\]]+)\]\s*", expr)
        if mm and mm.group(1) in self._measures:
            return self._eval_expr(self._measures[mm.group(1)], df_by_table, depth + 1)
        # arithmetic of measure references / numbers, e.g. [A] - [B]
        if re.fullmatch(r"[\s\[\]\w ().+\-*/]+", expr) and "[" in expr:
            def sub(match):
                val = self._eval_expr(f"[{match.group(1)}]", df_by_table, depth + 1)
                if val is None:
                    raise ValueError
                return repr(float(val))

            try:
                py = re.sub(r"\[([^\]]+)\]", sub, expr)
                if re.fullmatch(r"[\d\s.+\-*/()e]+", py):
                    return eval(py, {"__builtins__": {}}, {})  # digits/operators only
            except (ValueError, ZeroDivisionError, SyntaxError):
                return None
        try:
            return float(expr)
        except ValueError:
            return None

    def _value(self, field: dict, df_by_table: dict):
        if field["kind"] == "measure":
            expr = self._measures.get(field["name"])
            return None if expr is None else self._eval_expr(expr, df_by_table)
        df = df_by_table.get(field["table"])
        if df is None or field["name"] not in df:
            return None
        agg = field.get("agg") or ("sum" if str(df[field["name"]].dtype).startswith(("int", "float")) else "count")
        return self._agg(agg, df[field["name"]])

    def preview(self, fields: list[dict]) -> dict | None:
        """Return ``{"categories": [...], "series": [{"name", "values"}]}``
        (or ``{"value": x}`` / ``{"columns", "rows"}``) for a visual."""
        if not self._frames or not fields:
            return None
        cat_roles = {"Category", "Rows", "Axis", "Legend"}
        cats = [f for f in fields if f["role"] in cat_roles and f["kind"] == "column"]
        vals = [f for f in fields if f not in cats and f["kind"] in ("measure", "aggregation")]
        plain_cols = [f for f in fields if f["kind"] == "column" and f not in cats]

        if not cats and not vals and plain_cols:
            # table / slicer: show raw rows of the columns' table
            t = plain_cols[0]["table"]
            df = self._frames.get(t)
            if df is None:
                return None
            names = [f["name"] for f in plain_cols if f["table"] == t and f["name"] in df]
            if not names:
                return None
            sub = df[names].drop_duplicates().head(MAX_CATEGORIES)
            return {"columns": names, "rows": _jsonable(sub.values.tolist())}

        if cats:
            c = cats[0]
            base = self._frames.get(c["table"])
            if base is None or c["name"] not in base:
                return None
            categories = base[c["name"]].dropna().unique().tolist()
            try:
                categories = sorted(categories)
            except TypeError:
                pass
            categories = categories[:MAX_CATEGORIES]
            series = []
            for v in vals:
                values = []
                for cat in categories:
                    filtered = dict(self._frames)
                    filtered[c["table"]] = base[base[c["name"]] == cat]
                    values.append(self._value(v, filtered))
                series.append({"name": v["name"], "values": _jsonable(values)})
            if not series:
                return {"categories": _jsonable(categories), "series": []}
            if all(x is None for s in series for x in s["values"]):
                return None
            return {"categories": _jsonable(categories), "series": series}

        if vals:
            value = self._value(vals[0], dict(self._frames))
            return None if value is None else {"value": _jsonable([value])[0], "name": vals[0]["name"]}
        return None


def _jsonable(values: list) -> list:
    out = []
    for v in values:
        if isinstance(v, list):
            out.append(_jsonable(v))
            continue
        if v is None:
            out.append(None)
            continue
        try:
            if v != v:  # NaN
                out.append(None)
                continue
        except Exception:
            pass
        if hasattr(v, "item"):
            v = v.item()
        if hasattr(v, "isoformat"):
            v = v.isoformat()
        if not isinstance(v, (int, float, str, bool)):
            v = str(v)
        out.append(v)
    return out
