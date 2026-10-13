"""Rules over Stage 3A structured tables (strongest evidence).

* Label/value rows: a row with exactly two non-empty cells "<label> | <value>";
  the English part of the label is matched against the registry aliases.
* "Document required from seller": comma-separated list (+ "*" footnote kept).
* Consignee table: header row recognised by its column names; data rows map to
  consignees, addresses, quantities and delivery days (continuation tables on
  the next page are joined).
"""

from __future__ import annotations

import json
import re

from app.fields.constants import EvidenceType, Strength, ValueType
from app.fields.evidence import Candidate, Source, TableRef
from app.fields.labels import english_label, label_key
from app.fields.normalizers import Normalized, Rejected, clean, norm_list, normalize
from app.fields.registry import FIELDS, FieldSpec

DOCS_FIELD = "documents_required_from_seller"


def _pairs(row: list[str | None]) -> tuple[int, str, str] | None:
    """(label_col, label, value) when the row is a plain two-cell label/value row."""
    filled = [(i, c) for i, c in enumerate(row) if c is not None and clean(c)]
    if len(filled) != 2:
        return None
    (li, label), (_, value) = filled
    return li, label, value


def _section_ok(spec: FieldSpec, table: TableRef) -> bool:
    return spec.sections is None or (table.section is not None and table.section.normalized in spec.sections)


def parse_documents_list(raw: str) -> tuple[list[str], str | None]:
    """'Experience Criteria,Past Performance,Bidder\\nTurnover,...\\n*In case ...' ->
    (['Experience Criteria', 'Past Performance', 'Bidder Turnover', ...], '*In case ...')."""
    main, star, note = raw.partition("*")
    items = [clean(x) for x in " ".join(main.split()).split(",")]
    return [x for x in items if x], (clean(star + note) or None)


def _candidate(spec: FieldSpec, result, raw: str, label: str, table: TableRef, row_index: int,
               rule: str) -> Candidate:
    sec = table.section
    return Candidate(
        field_name=spec.name, result=result, raw_value=raw, evidence_type=EvidenceType.TABLE_CELL.value,
        strength=(Strength.SECTION_TABLE if spec.sections else Strength.EXACT_TABLE).value, rule=rule,
        source_label=label, page_number=table.page_number, table_id=table.id, table_index=table.table_index,
        row_index=row_index, section_id=sec.id if sec else None, section_heading=sec.normalized if sec else None,
        source_text=f"{label} | {clean(raw)}"[:500])


def label_value_candidates(src: Source, zone: str) -> list[Candidate]:
    out: list[Candidate] = []
    table_specs = [f for f in FIELDS if f.aliases]
    for table in src.tables:
        if is_consignee_header(table.rows[0] if table.rows else []):
            continue
        for r_i, row in enumerate(table.rows):
            pair = _pairs(row)
            if pair is None:
                continue
            label_col, label_cell, value = pair
            label = english_label(label_cell)
            key = label_key(label)
            if not key:
                continue
            for spec in table_specs:
                if not any(a.matches(key) for a in spec.aliases) or not _section_ok(spec, table):
                    continue
                rule = "section_table_label_alias" if spec.sections else "table_label_alias"
                if spec.name == DOCS_FIELD:
                    items, note = parse_documents_list(value)
                    result = norm_list(items)
                    if isinstance(result, Normalized) and note:
                        result.details["note"] = note
                    out.append(_candidate(spec, result, value, label, table, r_i, "documents_required_list"))
                    continue
                if spec.value_type == ValueType.LIST.value:
                    continue
                hint = "INR" if "inr" in key.split() else None
                if spec.value_type == ValueType.MONEY.value and "turnover" in key:
                    from app.fields.turnover import turnover_amount
                    value_col = next(i for i, cell in enumerate(row) if i != label_col and clean(cell))
                    header = clean(table.rows[0][value_col]) if r_i > 0 and value_col < len(table.rows[0]) else ""
                    header = header if re.match(r"^(?:value|amount|turnover)\b", header, re.I) else ""
                    result = turnover_amount(f"{label} {header}: {value}", hint) or Rejected("UNPARSEABLE")
                else:
                    result = normalize(spec.value_type, value, zone=zone, default_unit=spec.default_unit,
                                       currency_hint=hint)
                out.append(_candidate(spec, result, value, label, table, r_i, rule))
            # BIS requirement row ("Bis Required | Yes") -> certificate requirement
            if key == "bis required":
                b = normalize(ValueType.BOOL.value, value)
                if isinstance(b, Normalized) and b.value is True:
                    out.append(Candidate("certificate_requirements", norm_list(["BIS"]), value,
                                         EvidenceType.TABLE_CELL.value, Strength.EXACT_TABLE.value,
                                         "bis_required_table", label, table.page_number, table.id,
                                         table.table_index, r_i, table.section.id if table.section else None,
                                         table.section.normalized if table.section else None,
                                         f"{label} | {clean(value)}"))
    return out


# ---------------------------------------------------------------------------
# Consignee table
# ---------------------------------------------------------------------------
_COLS = (("consignee", "consignee"), ("address", "address"), ("delivery days", "delivery_days"),
         ("quantity", "quantity"), ("additional requirement", "additional"), ("s n", "sno"), ("s no", "sno"))


def _column_map(header: list[str | None]) -> dict[str, int]:
    cols: dict[str, int] = {}
    for i, cell in enumerate(header):
        key = label_key(english_label(cell or ""))
        for needle, name in _COLS:
            if name not in cols and (key == needle or key.startswith(needle + " ") or f" {needle} " in f" {key} "
                                     or key.endswith(" " + needle)):
                cols[name] = i
                break
    return cols


def is_consignee_header(row: list[str | None]) -> bool:
    cols = _column_map(row)
    return "consignee" in cols and ("quantity" in cols or "address" in cols)


def _unmask(v: str | None) -> str | None:
    s = re.sub(r"\*{3,}", " ", clean(v)).strip()
    return s or None


def consignee_candidates(src: Source) -> list[Candidate]:
    records: list[dict] = []
    first: tuple[TableRef, int] | None = None
    cols: dict[str, int] | None = None
    width = last_page = None
    for table in src.tables:
        rows = table.rows
        if rows and is_consignee_header(rows[0]):
            cols, width, start, last_page = _column_map(rows[0]), len(rows[0]), 1, table.page_number
        elif (cols is not None and rows and len(rows[0]) == width and clean(rows[0][0] or "").isdigit()
              and table.page_number == last_page + 1):
            start, last_page = 0, table.page_number  # continuation on the next page
        else:
            continue
        for r_i in range(start, len(rows)):
            row = rows[r_i]
            sno = clean(row[cols["sno"]]) if "sno" in cols and cols["sno"] < len(row) else ""
            if not sno.isdigit():
                continue

            def cell(name, cols=cols, row=row):
                i = cols.get(name)
                return row[i] if i is not None and i < len(row) else None

            qty = normalize(ValueType.INTEGER.value, cell("quantity") or "")
            days = normalize(ValueType.INTEGER.value, cell("delivery_days") or "")
            rec = {"sno": int(sno), "consignee": _unmask(cell("consignee")), "address": _unmask(cell("address")),
                   "address_raw": clean(cell("address")) or None,
                   "quantity": qty.value if isinstance(qty, Normalized) else None,
                   "delivery_days": days.value if isinstance(days, Normalized) else None,
                   "page": table.page_number, "table_index": table.table_index, "row_index": r_i}
            if cell("additional"):
                rec["additional_requirement"] = clean(cell("additional"))
            records.append(rec)
            if first is None:
                first = (table, r_i)
    if not records or first is None:
        return []
    table, r_i = first
    sec = table.section

    def cand(name: str, result, rule: str) -> Candidate:
        return Candidate(name, result, json.dumps(records, ensure_ascii=False)[:2000], EvidenceType.TABLE_ROW.value,
                         Strength.EXACT_TABLE.value, rule, "Consignees/Reporting Officer and Quantity",
                         table.page_number, table.id, table.table_index, r_i, sec.id if sec else None,
                         sec.normalized if sec else None, f"{len(records)} consignee row(s)")

    out = [cand("consignee_details", records_result(records), "consignee_table")]
    locations = [r["address"] for r in records if r["address"]]
    if locations:
        out.append(cand("delivery_locations", norm_list(locations), "consignee_table_address"))
    q = [{"sno": r["sno"], "consignee": r["consignee"], "address": r["address"], "quantity": r["quantity"]}
         for r in records if r["quantity"] is not None]
    if q:
        out.append(cand("quantity_by_consignee", records_result(q), "consignee_table_quantity"))
    days = sorted({r["delivery_days"] for r in records if r["delivery_days"] is not None})
    if len(days) == 1:
        out.append(cand("delivery_period", normalize(ValueType.DURATION.value, str(days[0]), default_unit="DAYS"),
                        "consignee_table_delivery_days"))
    elif days:
        per = [{"sno": r["sno"], "delivery_days": r["delivery_days"]} for r in records]
        out.append(cand("delivery_period",
                        Normalized({"varies_by_consignee": per}, "d:varies:" + ",".join(map(str, days)),
                                   "VARIES", unit="DAYS"), "consignee_table_delivery_days"))
    return out


def records_result(records: list[dict]) -> Normalized | Rejected:
    if not records:
        return Rejected("NOT_FOUND")
    key = "r:" + json.dumps(records, sort_keys=True, ensure_ascii=False)
    return Normalized(records, key[:255], f"{len(records)} record(s)")
