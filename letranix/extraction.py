"""Template-driven field extraction with per-field provenance.

Each extracted field records *how* it was found (``rule``), *where* (page, row,
box, evidence text), and whether it was read directly from a label
(``recognized``) or deduced (``inferred``). Nothing is filled in when no
evidence exists. The only score reported is the OCR engine's own recognition
score for the evidence row; no accuracy percentage is fabricated.
"""

import re
import unicodedata
from datetime import date
from itertools import combinations

SEPARATORS = r"[:=#\-–—]"
MONTHS = {
    "jan": 1, "janeiro": 1, "january": 1, "feb": 2, "fev": 2, "fevereiro": 2, "february": 2,
    "mar": 3, "marco": 3, "march": 3, "apr": 4, "abr": 4, "abril": 4, "april": 4,
    "may": 5, "mai": 5, "maio": 5, "jun": 6, "junho": 6, "june": 6, "jul": 7, "julho": 7,
    "july": 7, "aug": 8, "ago": 8, "agosto": 8, "august": 8, "sep": 9, "set": 9,
    "setembro": 9, "september": 9, "oct": 10, "out": 10, "outubro": 10, "october": 10,
    "nov": 11, "novembro": 11, "november": 11, "dec": 12, "dez": 12, "dezembro": 12,
    "december": 12,
}


def norm(text: str) -> str:
    """Lowercase, strip diacritics and collapse whitespace for label comparison."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def label_key(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", norm(text)).strip()


# --- Type normalisation ----------------------------------------------------


def parse_date(raw: str) -> tuple[str | None, list[str]]:
    s = norm(raw).replace(",", " ")
    s = re.sub(r"\s+", " ", s)
    m = re.search(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b", s)
    if m:
        return _iso(int(m[1]), int(m[2]), int(m[3])), []
    m = re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12 >= b:
            return _iso(y, b, a), []
        if b > 12 >= a:
            return _iso(y, a, b), ["Interpreted as month/day/year"]
        result = _iso(y, b, a)
        return result, (["Assumed day/month/year order"] if a != b else [])
    m = re.search(r"\b(\d{1,2})(?: de)? ([a-z]{3,9})\.?(?: de)? (\d{4})\b", s)
    if m and m[2] in MONTHS:
        return _iso(int(m[3]), MONTHS[m[2]], int(m[1])), []
    m = re.search(r"\b([a-z]{3,9})\.? (\d{1,2}) (\d{4})\b", s)
    if m and m[1] in MONTHS:
        return _iso(int(m[3]), MONTHS[m[1]], int(m[2])), []
    return None, []


def _iso(y, m, d):
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def parse_number(raw: str) -> str | None:
    s = re.sub(r"[^\d,.\-]", "", raw.replace(" ", ""))
    if not re.search(r"\d", s):
        return None
    negative = s.startswith("-")
    s = s.lstrip("-")
    last = max(s.rfind(","), s.rfind("."))
    if last != -1 and len(s) - last - 1 in (1, 2) and s.count(s[last]) == 1:
        integer, decimals = s[:last], s[last + 1 :]
    elif last != -1 and len(s) - last - 1 == 3 and s.count(s[last]) == 1 and (
        "," in s and "." in s
    ):
        integer, decimals = s[:last], s[last + 1 :]
    else:
        integer, decimals = s, ""
    integer = re.sub(r"[,.]", "", integer)
    if not integer.isdigit() and integer:
        return None
    value = (integer or "0") + ("." + decimals if decimals else "")
    return ("-" if negative else "") + value


def parse_money(raw: str) -> tuple[str | None, str]:
    currency = ""
    for symbol, code in (("r$", "BRL"), ("us$", "USD"), ("$", "USD"), ("eur", "EUR"),
                         ("€", "EUR"), ("brl", "BRL"), ("usd", "USD")):
        if symbol in raw.lower():
            currency = code
            break
    value = parse_number(raw)
    if value is not None and "." in value:
        integer, decimals = value.split(".")
        value = f"{integer}.{decimals.ljust(2, '0')}"
    elif value is not None:
        value = f"{value}.00"
    return value, currency


def normalize_value(raw: str, field: dict) -> tuple[str, list[str]]:
    """Return (normalised value, issues). Unparseable values are kept raw and flagged."""
    raw = re.sub(r"\s+", " ", raw).strip(" .;|")
    kind = field["type"]
    if not raw:
        return "", []
    if kind == "date":
        value, notes = parse_date(raw)
        return (value, notes) if value else (raw, ["Not a recognisable date"])
    if kind == "money":
        value, _currency = parse_money(raw)
        return (value, []) if value else (raw, ["Not a recognisable amount"])
    if kind == "number":
        value = parse_number(raw)
        return (value, []) if value else (raw, ["Not a number"])
    if kind == "identifier":
        value = re.sub(r"\s*([-/.])\s*", r"\1", raw).upper().split(" ")[0]
        return value, []
    if kind == "enum":
        n = label_key(raw)
        for option in field.get("options", []):
            o = label_key(option)
            if n == o or n.startswith(o + " ") or n.replace(" ", "-") == o:
                return option, []
        return raw, ["Not one of the allowed options"]
    return raw[:1000], []


def validate_value(value: str, field: dict) -> list[str]:
    issues = []
    if not value:
        return ["Required field missing"] if field.get("required") else []
    kind = field["type"]
    if kind == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        issues.append("Use ISO date YYYY-MM-DD")
    elif kind == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            issues.append("Invalid calendar date")
    if kind in {"money", "number"} and not re.fullmatch(r"-?\d+(\.\d+)?", value):
        issues.append("Use digits with an optional decimal point")
    if kind == "enum" and value not in field.get("options", []):
        issues.append("Not one of the allowed options")
    pattern = field.get("pattern")
    if pattern and not re.fullmatch(pattern, value):
        issues.append("Does not match the expected format")
    return issues


# --- Layout helpers --------------------------------------------------------


def cells(row: dict) -> list[dict]:
    """Split a row into cells: large horizontal gaps (OCR) or 2+ spaces/tabs/pipes (text)."""
    segs = row.get("segments") or []
    if segs:
        out = [dict(segs[0])]
        for seg in segs[1:]:
            prev = out[-1]
            height = max(1, prev["bbox"][3] - prev["bbox"][1])
            gap = seg["bbox"][0] - prev["bbox"][2]
            if gap > 1.6 * height:
                out.append(dict(seg))
            else:
                prev["text"] += " " + seg["text"]
                prev["bbox"] = [prev["bbox"][0], min(prev["bbox"][1], seg["bbox"][1]),
                                seg["bbox"][2], max(prev["bbox"][3], seg["bbox"][3])]
                prev["score"] = min(prev["score"], seg["score"])
        return out
    parts = [p for p in re.split(r"\t|\s{2,}|\s*\|\s*", row["text"]) if p.strip()]
    return [{"text": p.strip(), "bbox": None, "score": None} for p in parts]


def fold(text: str) -> tuple[str, list[int]]:
    """Lowercase and strip diacritics, keeping a map from folded to original indexes."""
    out, index = [], []
    for i, ch in enumerate(text):
        for d in unicodedata.normalize("NFKD", ch):
            if not unicodedata.combining(d):
                out.append(d.lower())
                index.append(i)
    return "".join(out), index


def _label_regex(labels: list[str]) -> re.Pattern:
    alternatives = sorted({label_key(x) for x in labels if label_key(x)}, key=len, reverse=True)
    # Spaces inside a label are optional: OCR often merges words ("Ordernumber").
    body = "|".join(re.escape(a).replace(r"\ ", r"\s*") for a in alternatives)
    return re.compile(
        rf"^\s*(?:{body})(?![a-z0-9])\.?(?:\s*(?:n[oº]\.?|number|num|#))?"
        rf"\s*(?P<sep>{SEPARATORS})?\s*(?P<value>.*?)\s*$",
        re.S,
    )


def _match_label(text: str, rx: re.Pattern) -> tuple[bool, str, bool]:
    """Match ``Label: value``; returns (matched, original-cased value, had separator)."""
    folded, index = fold(text)
    m = rx.match(folded)
    if not m:
        return False, "", False
    if not m["value"]:
        return True, "", bool(m["sep"])
    start = index[m.start("value")]
    end = index[m.end("value") - 1] + 1
    return True, text[start:end], bool(m["sep"])


def _evidence(page_no, row_index, row, cell=None):
    target = cell or row
    return {
        "page": page_no,
        "row": row_index,
        "evidence": row["text"][:300],
        "bbox": target.get("bbox") if target.get("bbox") is not None else row.get("bbox"),
        "ocr_score": target.get("score"),
    }


def find_labelled(pages: list[dict], labels: list[str], field: dict | None = None,
                  stop: re.Pattern | None = None) -> list[dict]:
    """All label matches in the document as candidate dicts with evidence.

    ``Label value`` without a separator is accepted only for typed fields whose
    value then parses cleanly, so prose such as "Description of work" is ignored.
    """
    rx = _label_regex(labels)
    found = []
    for page in pages:
        rows = page["rows"]
        for ri, row in enumerate(rows):
            row_cells = cells(row)
            for ci, cell in enumerate(row_cells):
                ok, value, sep = _match_label(cell["text"], rx)
                if not ok:
                    continue
                if value:
                    if not sep and (
                        field is None
                        or field["type"] == "text"
                        or normalize_value(value, field)[1]
                        or validate_value(normalize_value(value, field)[0], field)
                    ):
                        continue
                    found.append({"raw": value, "rule": "label", **_evidence(page["number"], ri, row, cell)})
                elif ci + 1 < len(row_cells) and not _is_label(row_cells[ci + 1]["text"], stop):
                    nxt = row_cells[ci + 1]
                    found.append({"raw": nxt["text"], "rule": "label-cell",
                                  **_evidence(page["number"], ri, row, nxt)})
                elif ri + 1 < len(rows):
                    below = _cell_below(cell, rows[ri + 1])
                    if below is not None and not _is_label_only(below["text"]) and not _is_label(
                        below["text"], stop
                    ):
                        found.append({"raw": below["text"], "rule": "label-below",
                                      **_evidence(page["number"], ri + 1, rows[ri + 1], below)})
    return found


def _is_label(text: str, stop: re.Pattern | None) -> bool:
    """Whether a cell is exactly another field's label (a column header, not a value)."""
    if stop is None:
        return False
    ok, value, _ = _match_label(text, stop)
    return ok and not value


def _is_label_only(text: str) -> bool:
    """A cell that is itself a label (``Name:``) or a ``Label: value`` pair is never a value below."""
    return bool(re.fullmatch(r"[^\W\d][\w ./()#-]{0,38}:(\s.*)?", text.strip()))


def _cell_below(cell: dict, row: dict):
    below_cells = cells(row)
    if not below_cells:
        return None
    if cell.get("bbox") is None:
        return below_cells[0] if len(below_cells) == 1 else None
    x0, x1 = cell["bbox"][0], cell["bbox"][2]
    best = None
    for c in below_cells:
        overlap = min(x1, c["bbox"][2]) - max(x0, c["bbox"][0])
        if overlap > 0 and (best is None or overlap > best[0]):
            best = (overlap, c)
    return best[1] if best else None


# --- Learned corrections -----------------------------------------------------


def apply_value_maps(value: str, rules: list[dict]):
    key = norm(value)
    for r in rules:
        if r["kind"] == "value-map" and r["pattern"] == key:
            return r["replacement"], r
    return None, None


def apply_char_maps(value: str, field: dict, rules: list[dict]):
    """Try learned character substitutions only when they turn an invalid value into a valid one."""
    maps = [r for r in rules if r["kind"] == "char-map"]
    if not maps or not validate_value(value, field):
        return None, None
    positions = []
    for r in maps:
        start = value.find(r["pattern"])
        while start != -1:
            positions.append((start, r))
            start = value.find(r["pattern"], start + 1)
    for size in (1, 2, 3):
        for combo in combinations(positions[:12], size):
            starts = [p for p, _ in combo]
            if len(set(starts)) != len(starts):
                continue
            candidate = value
            for start, r in sorted(combo, key=lambda x: -x[0]):
                candidate = candidate[:start] + r["replacement"] + candidate[start + len(r["pattern"]):]
            if not validate_value(candidate, field):
                return candidate, [r for _, r in combo]
    return None, None


# --- Main entry ------------------------------------------------------------


def extract_fields(pages: list[dict], template: dict, rules: list[dict], min_score: float) -> dict:
    """Return ``{"fields": {...}, "table": {...} | None, "pairs": [...]}``."""
    all_text = "\n".join(r["text"] for p in pages for r in p["rows"])
    fields = {}
    claimed = set()
    every_label = [lbl for f in template["fields"] for lbl in f["labels"]] + [
        r["pattern"] for r in rules if r["kind"] == "alias"
    ]
    stop = _label_regex(every_label)
    for field in template["fields"]:
        key = field["key"]
        field_rules = [r for r in rules if r["field"] == key]
        aliases = [r for r in field_rules if r["kind"] == "alias"]
        result = {"value": "", "raw": "", "source": "missing", "rule": "", "page": None,
                  "row": None, "evidence": "", "bbox": None, "ocr_score": None,
                  "ambiguous": False, "candidates": [], "issues": [], "learned": []}
        candidates = find_labelled(pages, field["labels"], field, stop)
        if not candidates and aliases:
            candidates = find_labelled(pages, [a["pattern"] for a in aliases], field, stop)
            for c in candidates:
                c["rule"] = "learned-alias"
            result["learned"] = [a["id"] for a in aliases]
        if candidates:
            priority = {"label": 0, "learned-alias": 0, "label-cell": 1, "label-below": 2}
            normalised = []
            for c in candidates:
                value, notes = normalize_value(c["raw"], field)
                valid = bool(value) and not validate_value(value, field)
                normalised.append((value, notes, c, valid))
            # Prefer values that validate, then direct "Label: value" matches over layout guesses.
            normalised.sort(key=lambda x: (not x[3], priority.get(x[2]["rule"], 3)))
            pool = [x for x in normalised if x[3]] or normalised
            distinct = list(dict.fromkeys(v for v, _, _, _ in pool if v))
            value, notes, chosen, _ = next((x for x in normalised if x[0]), normalised[0])
            result.update({k: chosen[k] for k in ("page", "row", "evidence", "bbox", "ocr_score", "rule")})
            result.update(value=value, raw=chosen["raw"], source="recognized" if value else "missing")
            result["issues"].extend(notes)
            if len(distinct) > 1:
                result["ambiguous"] = True
                result["candidates"] = distinct[:5]
                result["issues"].append(f"{len(distinct)} different values found; confirm the right one")
            claimed.add((chosen["page"], chosen["row"]))
        elif field["required"] and (field["type"] == "date" or field.get("pattern")):
            # Optional fields are never inferred: an absent optional value must stay empty.
            inferred = _unique_pattern(pages, field, claimed)
            if inferred:
                result.update(inferred)
                result["issues"].append("No label found; inferred from the only matching value")
                claimed.add((inferred["page"], inferred["row"]))
        if result["value"]:
            mapped, rule = apply_value_maps(result["value"], field_rules)
            if mapped is not None and mapped != result["value"]:
                result.update(value=mapped, source="inferred", rule="learned-value-map")
                result["learned"].append(rule["id"])
            fixed, used = apply_char_maps(result["value"], field, field_rules)
            if fixed is not None:
                result.update(value=fixed, source="inferred", rule="learned-char-map")
                result["learned"].extend(r["id"] for r in used)
        result["issues"].extend(i for i in validate_value(result["value"], field) if i not in result["issues"])
        if result["ocr_score"] is not None and result["ocr_score"] < min_score:
            result["issues"].append(f"Low OCR recognition score ({result['ocr_score']:.2f})")
        fields[key] = result
    table = extract_table(pages, template["table"]) if template.get("table") else None
    return {"fields": fields, "table": table, "pairs": labelled_pairs(pages, template), "chars": len(all_text)}


def _unique_pattern(pages, field, claimed):
    hits = []
    for page in pages:
        for ri, row in enumerate(page["rows"]):
            if (page["number"], ri) in claimed:
                continue
            for cell in cells(row):
                for token in re.findall(r"[\w/.\-]+", cell["text"]):
                    if field["type"] == "date":
                        value, _ = parse_date(token)
                    else:
                        value = token.upper() if re.fullmatch(field["pattern"], token.upper()) else None
                    if value:
                        hits.append((value, token, _evidence(page["number"], ri, row, cell)))
    values = {h[0] for h in hits}
    if len(values) != 1:
        return None
    value, token, ev = hits[0]
    return {"value": value, "raw": token, "source": "inferred", "rule": "unique-pattern", **ev}


def labelled_pairs(pages: list[dict], template: dict) -> list[dict]:
    """Generic ``Label: value`` pairs not covered by the template, to aid review and learning."""
    known = {label_key(lbl) for f in template["fields"] for lbl in f["labels"]}
    pairs = []
    for page in pages:
        for ri, row in enumerate(page["rows"]):
            for cell in cells(row):
                m = re.match(r"^([^\W\d][\w ./()-]{1,38}?)\s*:\s*(.+)$", cell["text"])
                if m and label_key(m[1]) not in known:
                    pairs.append({"label": m[1].strip(), "value": m[2].strip()[:200],
                                  "page": page["number"], "row": ri})
    return pairs[:40]


def extract_table(pages: list[dict], spec: dict) -> dict:
    columns = spec["columns"]
    label_sets = [{label_key(x) for x in c["labels"]} for c in columns]
    for page in pages:
        rows = page["rows"]
        for ri, row in enumerate(rows):
            header = cells(row)
            mapping = {}
            for hi, cell in enumerate(header):
                for ci, labels in enumerate(label_sets):
                    if label_key(cell["text"]) in labels and ci not in mapping.values():
                        mapping[hi] = ci
            if len(mapping) < 2:
                continue
            out_rows = []
            for rj in range(ri + 1, min(len(rows), ri + 200)):
                body = cells(rows[rj])
                if len(body) < 2:
                    break
                record = _assign(body, header, mapping, columns)
                if record is None:
                    break
                out_rows.append({"cells": record, "page": page["number"], "row": rj})
            return {
                "key": spec["key"],
                "columns": [c["key"] for c in columns],
                "rows": out_rows,
                "header": {"page": page["number"], "row": ri},
            }
    return {"key": spec["key"], "columns": [c["key"] for c in columns], "rows": [], "header": None}


def _assign(body, header, mapping, columns):
    record = {c["key"]: "" for c in columns}
    if body[0].get("bbox") is not None and header[0].get("bbox") is not None:
        centers = {hi: (header[hi]["bbox"][0] + header[hi]["bbox"][2]) / 2 for hi in mapping}
        for cell in body:
            cx = (cell["bbox"][0] + cell["bbox"][2]) / 2
            hi = min(centers, key=lambda h: abs(centers[h] - cx))
            col = columns[mapping[hi]]
            record[col["key"]] = (record[col["key"]] + " " + cell["text"]).strip()
    elif len(body) == len(header):
        for hi, ci in mapping.items():
            record[columns[ci]["key"]] = body[hi]["text"]
    else:
        return None
    if label_key(next(iter(record.values()), "")) in {"total", "subtotal"}:
        return None
    for col in columns:
        if record[col["key"]] and col["type"] in {"money", "number"}:
            value, _ = normalize_value(record[col["key"]], col)
            record[col["key"]] = value
    numeric = [c for c in columns if c["type"] in {"money", "number"}]
    if numeric and not any(re.fullmatch(r"-?\d+(\.\d+)?", record[c["key"]] or "") for c in numeric):
        return None  # A row without any numeric cell ends the table (e.g. a footer line).
    return record
