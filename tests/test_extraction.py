"""Unit tests for normalisation, label matching, layout rules and table extraction."""

import pytest

from letranix.extraction import (
    extract_fields,
    normalize_value,
    parse_date,
    parse_money,
    validate_value,
)
from letranix.templates import BUILTIN, validate_definition

T = {t["id"]: validate_definition(t) for t in BUILTIN}


def pages(text):
    return [{"number": 1, "rows": [{"text": ln, "segments": [], "bbox": None, "score": None}
                                    for ln in text.splitlines() if ln.strip()]}]


def ocr_row(*cells, y=100, score=0.95):
    """Build an OCR row from (text, x0, x1) cells at height y."""
    segs = [{"text": t, "bbox": [x0, y, x1, y + 30], "score": score} for t, x0, x1 in cells]
    return {"text": " ".join(s["text"] for s in segs), "segments": segs,
            "bbox": [cells[0][1], y, cells[-1][2], y + 30], "score": score}


@pytest.mark.parametrize("raw,expected", [
    ("2026-03-15", "2026-03-15"),
    ("15/03/2026", "2026-03-15"),
    ("15.03.2026", "2026-03-15"),
    ("2 Apr 2026", "2026-04-02"),
    ("15 de março de 2026", "2026-03-15"),
    ("April 2, 2026", "2026-04-02"),
    ("31/02/2026", None),
    ("soon", None),
])
def test_dates(raw, expected):
    assert parse_date(raw)[0] == expected


def test_ambiguous_day_month_is_flagged():
    value, notes = parse_date("03/04/2026")
    assert value == "2026-04-03" and notes == ["Assumed day/month/year order"]


@pytest.mark.parametrize("raw,value,currency", [
    ("R$ 1.234,56", "1234.56", "BRL"),
    ("$1,234.56", "1234.56", "USD"),
    ("254", "254.00", ""),
    ("EUR 99,9", "99.90", "EUR"),
    ("1 000,00", "1000.00", ""),
])
def test_money(raw, value, currency):
    assert parse_money(raw) == (value, currency)


def test_enum_and_identifier_normalisation():
    priority = next(f for f in T["service-order"]["fields"] if f["key"] == "priority")
    assert normalize_value("URGENT!", priority) == ("urgent", [])
    assert normalize_value("Alta", priority)[1] == ["Not one of the allowed options"]
    order = next(f for f in T["service-order"]["fields"] if f["key"] == "order_number")
    assert normalize_value("so - 123", order)[0] == "SO-123"
    assert validate_value("SO-12", order) == ["Does not match the expected format"]


def test_label_variants_separators_and_accents():
    text = "Order number - SO-5550\nSolicitante: Joana\nData: 01/02/2026\nPrioridade: normal\nDescrição: Teste"
    f = extract_fields(pages(text), T["service-order"], [], 0.6)["fields"]
    assert f["order_number"]["value"] == "SO-5550"
    assert f["requester"]["value"] == "Joana"
    assert f["date"]["value"] == "2026-02-01"
    assert f["description"]["value"] == "Teste"
    assert all(f[k]["source"] == "recognized" for k in ("order_number", "requester", "date"))


def test_prose_is_not_mistaken_for_a_label():
    f = extract_fields(pages("Description of the work follows below"), T["service-order"], [], 0.6)
    assert f["fields"]["description"]["value"] == ""


def test_missing_optional_fields_are_never_invented():
    text = "Invoice No.: INV-1000\nIssuer: A\nBill to: B\nInvoice date: 2026-01-01\nTotal: 10"
    f = extract_fields(pages(text), T["invoice"], [], 0.6)["fields"]
    assert f["due_date"]["value"] == ""  # Optional and absent.
    assert f["issue_date"]["value"] == "2026-01-01"
    assert f["issue_date"]["source"] == "inferred"  # Required, unique date, unknown label.


def test_ambiguity_lists_candidates():
    f = extract_fields(pages("Requested by: Ana\nRequested by: Bia"), T["service-order"], [], 0.6)
    requester = f["fields"]["requester"]
    assert requester["ambiguous"] and requester["candidates"] == ["Ana", "Bia"]


def test_layout_label_below_and_low_score():
    doc = [{"number": 1, "rows": [
        ocr_row(("Order number", 50, 300), ("Priority", 700, 860), y=100),
        ocr_row(("SO-20981", 50, 260), ("Urgent", 700, 830), y=160, score=0.42),
    ]}]
    f = extract_fields(doc, T["service-order"], [], 0.6)["fields"]
    assert f["order_number"]["value"] == "SO-20981"
    assert f["order_number"]["rule"] == "label-below"
    assert f["priority"]["value"] == "urgent"
    assert f["priority"]["bbox"] == [700, 160, 830, 190]
    assert any("Low OCR" in i for i in f["priority"]["issues"])


def test_table_extraction_native_text():
    text = (
        "Invoice No.: INV-2087\nDescription            Qty    Unit price    Amount\n"
        "Archive labels          10          2.50     25.00\n"
        "Scanner calibration      1        180.00    180.00\nTotal: 205.00"
    )
    table = extract_fields(pages(text), T["invoice"], [], 0.6)["table"]
    assert [r["cells"] for r in table["rows"]] == [
        {"description": "Archive labels", "quantity": "10", "unit_price": "2.50", "amount": "25.00"},
        {"description": "Scanner calibration", "quantity": "1", "unit_price": "180.00", "amount": "180.00"},
    ]


def test_learned_rules_are_applied_and_marked_inferred():
    rules = [
        {"id": "a" * 32, "field": "requester", "kind": "alias", "pattern": "raised by", "replacement": ""},
        {"id": "b" * 32, "field": "order_number", "kind": "char-map", "pattern": "O", "replacement": "0"},
        {"id": "c" * 32, "field": "priority", "kind": "value-map", "pattern": "alta", "replacement": "high"},
    ]
    text = "Order No.: SO-1O23\nRaised by: Caio\nPriority: Alta"
    f = extract_fields(pages(text), T["service-order"], rules, 0.6)["fields"]
    assert f["requester"]["value"] == "Caio" and f["requester"]["rule"] == "learned-alias"
    assert f["order_number"]["value"] == "SO-1023" and f["order_number"]["source"] == "inferred"
    assert f["priority"]["value"] == "high" and f["priority"]["rule"] == "learned-value-map"


@pytest.mark.parametrize("bad", [
    {"id": "X", "name": "n", "fields": [{"key": "a"}]},
    {"id": "ok-id", "name": "n", "fields": []},
    {"id": "ok-id", "name": "n", "fields": [{"key": "a", "pattern": "("}]},
    {"id": "ok-id", "name": "n", "fields": [{"key": "a", "type": "enum"}]},
    {"id": "ok-id", "name": "n", "fields": [{"key": "a"}, {"key": "a"}]},
    {"id": "ok-id", "name": "n", "fields": [{"key": "a"}], "extra": 1},
])
def test_template_validation(bad):
    with pytest.raises(ValueError):
        validate_definition(bad)
