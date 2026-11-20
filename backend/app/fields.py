"""Conversion between Power BI semantic-query field expressions and the
editor's simple field dicts.

Editor field: ``{"role": "Y", "kind": "column|measure|aggregation|other",
"table": "Sales", "name": "Amount", "agg": "sum"}``.
"""

from __future__ import annotations

# QueryAggregateFunction codes used by Power BI.
AGG_CODES = {
    0: "sum",
    1: "average",
    2: "count",
    3: "min",
    4: "max",
    5: "countNonNull",
    6: "median",
    7: "stdDev",
    8: "variance",
}
AGG_NAMES = {v: k for k, v in AGG_CODES.items()}
AGG_QUERYREF = {
    "sum": "Sum",
    "average": "Avg",
    "count": "Count",
    "min": "Min",
    "max": "Max",
    "countNonNull": "CountNonNull",
    "median": "Median",
    "stdDev": "StandardDeviation",
    "variance": "Variance",
}


def _entity(source_ref: dict, aliases: dict[str, str]) -> str | None:
    if "Entity" in source_ref:
        return source_ref["Entity"]
    return aliases.get(source_ref.get("Source", ""))


def expr_to_field(expr: dict, aliases: dict[str, str] | None = None) -> dict:
    aliases = aliases or {}
    if "Column" in expr or "Measure" in expr:
        kind = "column" if "Column" in expr else "measure"
        node = expr[kind.capitalize()]
        src = node.get("Expression", {}).get("SourceRef", {})
        return {"kind": kind, "table": _entity(src, aliases), "name": node.get("Property")}
    if "Aggregation" in expr:
        agg = expr["Aggregation"]
        inner = expr_to_field(agg.get("Expression", {}), aliases)
        inner["kind"] = "aggregation"
        inner["agg"] = AGG_CODES.get(agg.get("Function"), "sum")
        return inner
    if "HierarchyLevel" in expr:
        lvl = expr["HierarchyLevel"]
        hier = lvl.get("Expression", {}).get("Hierarchy", {})
        src = hier.get("Expression", {}).get("SourceRef", {})
        if not src:  # variation source
            src = (
                hier.get("Expression", {})
                .get("PropertyVariationSource", {})
                .get("Expression", {})
                .get("SourceRef", {})
            )
        return {"kind": "other", "table": _entity(src, aliases), "name": lvl.get("Level")}
    return {"kind": "other", "table": None, "name": None}


def field_to_expr(f: dict) -> dict:
    """Field expression using an Entity SourceRef (PBIR style)."""
    ref = {"Expression": {"SourceRef": {"Entity": f["table"]}}, "Property": f["name"]}
    if f["kind"] == "measure":
        return {"Measure": ref}
    if f["kind"] == "aggregation":
        return {"Aggregation": {"Expression": {"Column": ref}, "Function": AGG_NAMES.get(f.get("agg", "sum"), 0)}}
    return {"Column": ref}


def query_ref(f: dict) -> str:
    base = f"{f['table']}.{f['name']}"
    if f["kind"] == "aggregation":
        return f"{AGG_QUERYREF.get(f.get('agg', 'sum'), 'Sum')}({base})"
    return base


def native_ref(f: dict) -> str:
    if f["kind"] == "aggregation":
        label = {"average": "Average of", "countNonNull": "Count of"}.get(
            f.get("agg", "sum"), f"{AGG_QUERYREF.get(f.get('agg', 'sum'), 'Sum')} of"
        )
        return f"{label} {f['name']}"
    return f["name"]


def literal_text(value: str) -> dict:
    return {"expr": {"Literal": {"Value": "'" + value.replace("'", "''") + "'"}}}


def read_literal_text(prop: dict | None) -> str | None:
    try:
        v = prop["expr"]["Literal"]["Value"]
    except (TypeError, KeyError):
        return None
    if isinstance(v, str) and len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return None


def title_objects(title: str) -> list[dict]:
    """Title formatting; an empty title hides the title bar."""
    show = "true" if title else "false"
    return [{"properties": {"show": {"expr": {"Literal": {"Value": show}}}, "text": literal_text(title)}}]


def title_changed(new: str | None, old: str | None) -> bool:
    return new is not None and (new or None) != (old or None)


def read_title(vc_objects: dict | None) -> str | None:
    try:
        return read_literal_text(vc_objects["title"][0]["properties"].get("text"))
    except (TypeError, KeyError, IndexError):
        return None
