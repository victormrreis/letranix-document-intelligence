"""Learning from human review.

Two mechanisms, both inspectable and reversible:

1. **Correction rules** derived from approved reviews:
   - ``alias``: a label the reviewer's confirmed value sat next to, which the
     template did not know (e.g. "Raised by" for *requester*).
   - ``value-map``: a recurring whole-value correction (e.g. OCR "Exarnple" ->
     "Example", or "Alta" -> "high" for an enum).
   - ``char-map``: a recurring character confusion (e.g. ``O`` -> ``0``), applied
     only when it turns an invalid value into one that passes validation.
   A rule is *active* once it has been confirmed on ``learning.min_support``
   distinct documents. Rules record how often they were applied.

2. **Document-type classifier**: multinomial Naive Bayes over word tokens,
   trained on approved documents plus each template's keywords and labels as a
   prior pseudo-document. It is re-fitted from the database when the set of
   approved reviews changes; this is statistical learning from confirmed
   examples, not a neural model.
"""

import difflib
import json
import math
import re
import threading
from collections import Counter

from .db import audit, now, uid
from .extraction import cells, label_key, norm, normalize_value

STOP = {"the", "and", "for", "with", "from", "this", "that", "de", "da", "do", "das", "dos",
        "para", "com", "por", "uma", "synthetic", "demonstration", "document", "not"}


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z]{3,}", norm(text)) if t not in STOP]


class Classifier:
    def __init__(self):
        self._lock = threading.Lock()
        self._key = None
        self._model = None

    def fit(self, examples: list[tuple[str, str]], templates: list[dict]):
        counts: dict[str, Counter] = {}
        docs: Counter = Counter()
        for t in templates:
            prior = " ".join(t.get("keywords", []) + [lbl for f in t["fields"] for lbl in f["labels"]])
            counts[t["id"]] = Counter(tokens(prior) * 2)
            docs[t["id"]] += 1
        for text, label in examples:
            if label in counts:
                counts[label].update(tokens(text))
                docs[label] += 1
        vocab = set().union(*counts.values()) if counts else set()
        totals = {k: sum(c.values()) for k, c in counts.items()}
        n_docs = sum(docs.values())
        keywords = sorted({k for t in templates for k in t.get("keywords", []) if " " in k})
        return {"counts": counts, "docs": docs, "vocab": len(vocab) or 1, "totals": totals,
                "n": n_docs, "examples": len(examples), "keywords": keywords}

    def model(self, db, templates: list[dict]):
        with db.connect() as c:
            key = c.execute(
                "SELECT COUNT(*), MAX(created) FROM reviews WHERE decision='approved'"
            ).fetchone()
            key = (tuple(key), tuple(sorted(t["id"] for t in templates)))
            with self._lock:
                if key == self._key:
                    return self._model
            rows = c.execute(
                """SELECT d.text, r.template_id FROM reviews r JOIN documents d ON d.id=r.document_id
                WHERE r.decision='approved' AND r.id = (SELECT id FROM reviews r2
                  WHERE r2.document_id=r.document_id AND r2.decision='approved'
                  ORDER BY created DESC LIMIT 1)"""
            ).fetchall()
        model = self.fit([(r["text"], r["template_id"]) for r in rows], templates)
        with self._lock:
            self._key, self._model = key, model
        return model

    @staticmethod
    def predict(model, text: str) -> list[dict]:
        words = Counter(tokens(text))
        # OCR often drops spaces in headings ("SERVICEORDER"); recover multi-word keywords.
        compact = re.sub(r"[^a-z]", "", norm(text))
        spaced = norm(text)
        for keyword in model.get("keywords", []):
            if keyword not in spaced and keyword.replace(" ", "") in compact:
                words.update(tokens(keyword))
        scores = {}
        for label, counts in model["counts"].items():
            score = math.log(model["docs"][label] / model["n"])
            denominator = model["totals"][label] + model["vocab"]
            for word, n in words.items():
                score += n * math.log((counts.get(word, 0) + 1) / denominator)
            scores[label] = score
        if not scores:
            return []
        top = max(scores.values())
        exp = {k: math.exp(v - top) for k, v in scores.items()}
        total = sum(exp.values())
        ranked = sorted(((k, v / total) for k, v in exp.items()), key=lambda x: -x[1])
        return [{"template": k, "probability": round(p, 4)} for k, p in ranked[:4]]


def active_rules(c, template_id: str, min_support: int) -> list[dict]:
    rows = c.execute(
        "SELECT * FROM rules WHERE template_id=? AND enabled=1 AND support>=?",
        (template_id, min_support),
    ).fetchall()
    return [dict(r) for r in rows]


def _upsert_rule(c, template_id, field, kind, pattern, replacement, document_id, actor):
    row = c.execute(
        "SELECT * FROM rules WHERE template_id=? AND field=? AND kind=? AND pattern=? AND replacement=?",
        (template_id, field, kind, pattern, replacement),
    ).fetchone()
    if row is None:
        rule_id = uid()
        c.execute(
            "INSERT INTO rules(id,template_id,field,kind,pattern,replacement,support,created,updated) "
            "VALUES(?,?,?,?,?,?,0,?,?)",
            (rule_id, template_id, field, kind, pattern, replacement, now(), now()),
        )
    else:
        rule_id = row["id"]
    return _add_support(c, rule_id, document_id, actor, "learned")


def _add_support(c, rule_id, document_id, actor, reason):
    """Count a document as evidence for a rule once, however often it is re-reviewed."""
    inserted = c.execute(
        "INSERT OR IGNORE INTO rule_support(rule_id, document_id, created) VALUES(?,?,?)",
        (rule_id, document_id, now()),
    ).rowcount
    if inserted:
        c.execute(
            "UPDATE rules SET support=(SELECT COUNT(*) FROM rule_support WHERE rule_id=?), updated=? "
            "WHERE id=?",
            (rule_id, now(), rule_id),
        )
        audit(c, document_id, "learning.rule-evidence", actor, {"rule": rule_id, "reason": reason})
    return rule_id


def learn_from_review(c, doc, template: dict, confirmed: dict, review_id: str, actor: str) -> list[str]:
    """Record corrections for an approved review and derive rule evidence. Returns rule ids."""
    extracted = json.loads(doc["fields"])
    pages = [
        {"number": p["page"], "rows": json.loads(p["rows"])}
        for p in c.execute(
            "SELECT page, rows FROM pages WHERE document_id=? AND version=? ORDER BY page",
            (doc["id"], doc["version"]),
        )
    ]
    learned = []
    for field in template["fields"]:
        key = field["key"]
        got = extracted.get(key, {})
        before = got.get("value", "")
        after = confirmed.get(key, "").strip()
        used = [rid for rid in got.get("learned", []) if got.get("rule", "").startswith("learned")]
        if before == after:
            for rule_id in used:  # A learned value the reviewer confirmed is further evidence.
                learned.append(_add_support(c, rule_id, doc["id"], actor, "confirmed"))
            continue
        for rule_id in used:  # A learned value the reviewer corrected counts against the rule.
            c.execute(
                "UPDATE rules SET rejected=rejected+1, enabled=CASE WHEN rejected+1>support THEN 0 "
                "ELSE enabled END, updated=? WHERE id=?",
                (now(), rule_id),
            )
            audit(c, doc["id"], "learning.rule-contradicted", actor, {"rule": rule_id, "field": key})
        c.execute(
            "INSERT INTO corrections VALUES(?,?,?,?,?,?,?,?,?)",
            (uid(), review_id, doc["id"], template["id"], key, before, after,
             got.get("source", "missing"), now()),
        )
        if not after:
            continue
        if got.get("source", "missing") == "missing" or got.get("rule") == "unique-pattern":
            maps = {r["pattern"]: r["replacement"] for r in c.execute(
                "SELECT pattern, replacement FROM rules WHERE template_id=? AND field=? AND kind='value-map' "
                "AND enabled=1", (template["id"], key))}
            for label in _labels_for_value(pages, after, field, maps):
                learned.append(_upsert_rule(c, template["id"], key, "alias", label, "", doc["id"], actor))
        elif before:
            if field["type"] in {"text", "enum"}:
                similar = difflib.SequenceMatcher(None, norm(before), norm(after)).ratio()
                if field["type"] == "enum" or similar >= 0.6:
                    learned.append(_upsert_rule(c, template["id"], key, "value-map", norm(before),
                                                after, doc["id"], actor))
            else:
                for a, b in _char_confusions(before, after):
                    learned.append(_upsert_rule(c, template["id"], key, "char-map", a, b,
                                                doc["id"], actor))
    return learned


def _labels_for_value(pages, value: str, field: dict, maps: dict | None = None) -> list[str]:
    """Find label text adjacent to a confirmed value: same cell, next cell or the row above."""
    found = []
    for page in pages:
        rows = page["rows"]
        for ri, row in enumerate(rows):
            row_cells = cells(row)
            for ci, cell in enumerate(row_cells):
                m = re.match(r"^\s*([^\W\d][\w .#/()-]{0,38}?)\s*[:=]\s*(.+)$", cell["text"])
                if m and _same(m[2], value, field, maps):
                    found.append(m[1])
                elif _same(cell["text"], value, field, maps):
                    if ci > 0 and re.fullmatch(r"[^\W\d][\w .#/()-]{0,38}:?", row_cells[ci - 1]["text"]):
                        found.append(row_cells[ci - 1]["text"])
                    elif ri > 0:
                        above = cells(rows[ri - 1])
                        if len(above) == 1 and re.fullmatch(r"[^\W\d][\w .#/()-]{0,38}:?", above[0]["text"]):
                            found.append(above[0]["text"])
    labels = []
    for label in found:
        key = label_key(label.rstrip(":"))
        if 2 <= len(key) <= 40 and key not in labels:
            labels.append(key)
    return labels[:2]


def _same(raw: str, value: str, field: dict, maps: dict | None = None) -> bool:
    """Whether a raw document value means the confirmed value, directly or via a known value-map."""
    normalised, _ = normalize_value(raw, field)
    if normalised == value or norm(raw) == norm(value):
        return True
    return bool(maps) and maps.get(norm(normalised)) == value


def _char_confusions(before: str, after: str) -> list[tuple[str, str]]:
    ops = difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
    changes = [(before[i1:i2], after[j1:j2]) for tag, i1, i2, j1, j2 in ops if tag != "equal"]
    if not changes or len(changes) > 3:
        return []
    if any(not a or not b or len(a) > 2 or len(b) > 2 for a, b in changes):
        return []
    return list(dict.fromkeys(changes))
