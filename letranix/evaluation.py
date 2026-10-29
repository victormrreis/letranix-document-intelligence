"""Reproducible measurement of what learning from review actually changes.

Synthetic documents are generated with three independent seeds:

- **train**: imported, processed and approved through the real service with the
  ground truth as the reviewer's input; this is the only source of learning;
- **validation**: chooses ``learning.min_support``;
- **test**: reported once, before learning (template knowledge only) and after.

The generator mixes labels the templates know with recurring labels they do
not (a supplier's own wording), OCR-style character confusions in identifiers,
Portuguese option synonyms and absent optional fields. Field values are drawn
independently per split, so the test set cannot be solved by memorising
values. Metrics are exact matches against normalised ground truth; ``invented``
counts values produced where the ground truth is empty (should stay 0).
"""

import json
import random
import shutil
import tempfile
import time
from pathlib import Path

from .extraction import extract_fields
from .learning import Classifier, active_rules
from .service import Letranix

NOVEL = {
    "service-order": {
        "order_number": ["Ticket", "WO #", "Job reference"],
        "requester": ["Raised by", "Contact person"],
        "date": ["Opened on", "Logged"],
        "priority": ["Urgency"],
        "description": ["Work requested", "Scope"],
        "location": ["Area"],
    },
    "invoice": {
        "invoice_number": ["Bill ref", "Document no"],
        "issuer": ["Supplier", "Vendor"],
        "customer": ["Sold to", "Client"],
        "issue_date": ["Invoice date", "Dated"],
        "total": ["Grand total", "Balance"],
    },
    "inspection-report": {
        "report_id": ["Check ref", "Audit no"],
        "inspector": ["Checked by", "Auditor"],
        "site": ["Facility", "Plant"],
        "date": ["Visited", "Checked on"],
        "result": ["Verdict", "Status"],
    },
    "administrative-request": {
        "protocol": ["Case no", "Ticket id"],
        "requester": ["Submitted by", "Petitioner"],
        "department": ["Unit", "Division"],
        "subject": ["Regarding", "Topic"],
    },
}
SYNONYMS = {
    "priority": {"high": ["Alta", "High"], "urgent": ["Urgente", "Urgent"], "low": ["Baixa", "Low"],
                 "normal": ["Normal", "Media"]},
    "result": {"pass": ["Aprovado", "Pass"], "fail": ["Reprovado", "Fail"], "conditional": ["Condicional"]},
}
PREFIX = {"order_number": "SO", "invoice_number": "INV", "report_id": "IR", "protocol": "AR"}
SYLLABLES = ["ana", "bel", "car", "dor", "eli", "fer", "gal", "hel", "ivo", "jun", "kel", "lor",
             "mar", "nel", "oto", "pra", "qui", "ros", "sam", "tia", "ula", "val", "wes", "xan"]


def _name(rng):
    return " ".join("".join(rng.choice(SYLLABLES) for _ in range(2)).title() for _ in range(2))


def _value(rng, template, field):
    key, kind = field["key"], field["type"]
    if kind == "identifier":
        prefix = PREFIX.get(key, "ID")
        return f"{prefix}-{rng.randint(1000, 99999)}"
    if kind == "date":
        return f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
    if kind == "money":
        return f"{rng.randint(10, 9000)}.{rng.choice(['00', '50', '25', '99'])}"
    if kind == "number":
        return str(rng.randint(1, 500))
    if kind == "enum":
        return rng.choice(field["options"])
    if key in {"description", "subject", "notes"}:
        return f"Synthetic task {rng.randint(100, 999)} for {_name(rng).split()[0]}"
    if key in {"site", "location", "department"}:
        return f"{rng.choice(['North', 'South', 'East', 'West'])} {_name(rng).split()[0]} Unit"
    return _name(rng)


def _render_value(rng, field, truth):
    if field["type"] == "date":
        y, m, d = truth.split("-")
        return rng.choice([truth, f"{d}/{m}/{y}", f"{int(d)} {['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][int(m)-1]} {y}"])
    if field["type"] == "money":
        return rng.choice([f"${truth}", f"R$ {truth.replace('.', ',')}", truth])
    if field["type"] == "enum" and field["key"] in SYNONYMS:
        return rng.choice(SYNONYMS[field["key"]].get(truth, [truth]))
    if field["type"] == "identifier" and rng.random() < 0.35:
        prefix, digits = truth.split("-")
        if "0" in digits:
            return f"{prefix}-{digits.replace('0', 'O', 1)}"  # OCR-style confusion
        if "1" in digits:
            return f"{prefix}-{digits.replace('1', 'I', 1)}"
    return truth


def generate_split(seed: int, n: int, templates: dict) -> list[dict]:
    rng = random.Random(seed)  # nosec B311 - reproducible synthetic data, not security
    docs = []
    ids = list(NOVEL)
    for i in range(n):
        template = templates[ids[i % len(ids)]]
        truth, lines = {}, []
        heading = rng.choice(template["keywords"][:2]).upper() if rng.random() < 0.5 else "RECORD"
        lines.append(heading)
        for field in template["fields"]:
            if not field["required"] and rng.random() < 0.4:
                truth[field["key"]] = ""
                continue
            truth[field["key"]] = _value(rng, template, field)
            novel = NOVEL[template["id"]].get(field["key"], [])
            label = rng.choice(novel) if novel and rng.random() < 0.5 else field["labels"][0].title()
            lines.append(f"{label}: {_render_value(rng, field, truth[field['key']])}")
        body = lines[:1] + rng.sample(lines[1:], len(lines) - 1)
        docs.append({"name": f"eval-{seed}-{i}.txt", "template": template["id"], "truth": truth,
                     "text": "\n".join(body) + "\n"})
    return docs


def _pages(text: str):
    return [{"number": 1, "rows": [{"text": ln, "segments": [], "bbox": None, "score": None}
                                    for ln in text.splitlines() if ln.strip()]}]


def score(docs, model, rules_by_template, templates, use_predicted=True) -> dict:
    total = correct = invented = typed_correct = 0
    per_field: dict[str, list[int]] = {}
    template_hits = 0
    for doc in docs:
        prediction = Classifier.predict(model, doc["text"])
        predicted = prediction[0]["template"] if prediction else "generic-record"
        template_hits += predicted == doc["template"]
        tid = predicted if use_predicted else doc["template"]
        result = extract_fields(_pages(doc["text"]), templates[tid], rules_by_template.get(tid, []), 0.0)
        values = {k: v["value"] for k, v in result["fields"].items()} if tid == doc["template"] else {}
        for key, truth in doc["truth"].items():
            got = values.get(key, "")
            if truth:
                total += 1
                hit = got == truth
                correct += hit
                per_field.setdefault(f"{doc['template']}.{key}", [0, 0])
                per_field[f"{doc['template']}.{key}"][0] += hit
                per_field[f"{doc['template']}.{key}"][1] += 1
                typed_correct += hit
            elif got:
                invented += 1
    return {
        "documents": len(docs),
        "template_accuracy": round(template_hits / len(docs), 4),
        "field_accuracy": round(correct / total, 4) if total else None,
        "fields_evaluated": total,
        "invented_values": invented,
        "per_field": {k: round(a / b, 3) for k, (a, b) in sorted(per_field.items())},
    }


def run_evaluation(workdir: Path, save_to: Path | None = None, sizes=(60, 30, 60), seeds=(11, 22, 33)) -> dict:
    started = time.perf_counter()
    workdir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=workdir, prefix="run-"))
    svc = Letranix(tmp, start_workers=False)
    try:
        svc.settings.update({"learning.min_support": 1, "review.require_approval_reason": False})
        templates = {t["id"]: t for t in svc.templates.all()}
        train, validation, test = (generate_split(s, n, templates) for s, n in zip(seeds, sizes))
        baseline_model = svc.classifier.fit([], list(templates.values()))
        before = score(test, baseline_model, {}, templates)

        for doc in train:  # The real import -> process -> correct -> approve path.
            r = svc.import_bytes(doc["name"], doc["text"].encode(), "evaluation", via="evaluation")
            while svc.run_next_job():
                pass
            d = svc.get(r["id"])
            if d["template_id"] != doc["template"]:
                svc.apply_template(r["id"], doc["template"], "evaluation")
                d = svc.get(r["id"])
            svc.review(r["id"], {"version": d["version"], "decision": "approved", "actor": "evaluation",
                                 "reason": "", "fields": doc["truth"], "issues": {}, "table": []})
        model = svc.classifier.model(svc.db, list(templates.values()))

        def rules_at(k):
            with svc.db.connect() as c:
                return {tid: active_rules(c, tid, k) for tid in templates}

        selection = {k: score(validation, model, rules_at(k), templates)["field_accuracy"] for k in (1, 2, 3)}
        chosen = max(selection, key=lambda k: (selection[k], -k))
        after = score(test, model, rules_at(chosen), templates)
        with svc.db.connect() as c:
            rule_counts = dict(c.execute(
                "SELECT kind, COUNT(*) FROM rules WHERE support>=? GROUP BY kind", (chosen,)).fetchall())
        report = {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "method": "Synthetic text documents; exact match on normalised values; separate seeds per split.",
            "splits": {"train": len(train), "validation": len(validation), "test": len(test)},
            "seeds": dict(zip(("train", "validation", "test"), seeds)),
            "min_support_selection": selection,
            "min_support_chosen": chosen,
            "rules_active": rule_counts,
            "test_before_learning": before,
            "test_after_learning": after,
            "seconds": round(time.perf_counter() - started, 2),
        }
    finally:
        svc.close()
        shutil.rmtree(tmp, ignore_errors=True)
    if save_to is not None:
        (save_to / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def latest_report(root: Path) -> dict | None:
    path = root / "evaluation.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
