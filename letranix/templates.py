"""Document type templates: expected fields, their labels, types and validation rules.

Built-in templates describe generic, invented document types. Users can add
their own through the API; definitions are validated before storage.
"""

import json
import re

from .db import Database, audit, now

FIELD_TYPES = {"text", "identifier", "date", "number", "money", "enum"}
SLUG = re.compile(r"^[a-z][a-z0-9-]{1,39}$")


def _f(key, label, type_, labels, required=True, **extra):
    return {"key": key, "label": label, "type": type_, "labels": labels, "required": required, **extra}


BUILTIN = [
    {
        "id": "generic-record",
        "name": "Generic record",
        "description": "Five labelled fields. Compatible with LETRANIX 0.1 workspaces.",
        "keywords": [],
        "fields": [
            _f("reference", "Reference", "identifier", ["reference", "referencia", "ref"]),
            _f("organization", "Organization", "text", ["organization", "organizacao", "org"]),
            _f(
                "category", "Category", "enum", ["category", "categoria"],
                options=["service-order", "operational-report", "administrative-request",
                         "handwritten-form"],
            ),
            _f("date", "Date", "date", ["date", "data"]),
            _f("description", "Description", "text", ["description", "descricao"]),
        ],
    },
    {
        "id": "service-order",
        "name": "Service order",
        "description": "Work request with requester, schedule and priority.",
        "keywords": ["service order", "work order", "ordem de servico", "maintenance request"],
        "fields": [
            _f("order_number", "Order number", "identifier",
               ["order number", "order no", "order", "numero da ordem", "os"],
               pattern=r"^[A-Z]{2,5}-\d{3,8}$"),
            _f("requester", "Requester", "text", ["requester", "requested by", "solicitante"]),
            _f("location", "Location", "text", ["location", "site", "local"], required=False),
            _f("date", "Request date", "date", ["date", "request date", "data"]),
            _f("due_date", "Due date", "date", ["due date", "deadline", "prazo"], required=False),
            _f("priority", "Priority", "enum", ["priority", "prioridade"],
               options=["low", "normal", "high", "urgent"]),
            _f("description", "Description", "text", ["description", "descricao", "task"]),
        ],
    },
    {
        "id": "invoice",
        "name": "Invoice",
        "description": "Billing document with totals and optional line items.",
        "keywords": ["invoice", "fatura", "nota", "bill to", "amount due", "subtotal"],
        "fields": [
            _f("invoice_number", "Invoice number", "identifier",
               ["invoice number", "invoice no", "invoice", "fatura", "numero"],
               pattern=r"^[A-Z]{2,5}-\d{3,8}$"),
            _f("issuer", "Issuer", "text", ["issuer", "from", "seller", "emitente"]),
            _f("customer", "Customer", "text", ["customer", "bill to", "cliente"]),
            _f("issue_date", "Issue date", "date", ["issue date", "date", "data de emissao"]),
            _f("due_date", "Due date", "date", ["due date", "vencimento"], required=False),
            _f("total", "Total", "money", ["total", "amount due", "total due", "valor total"]),
        ],
        "table": {
            "key": "items",
            "label": "Line items",
            "columns": [
                {"key": "description", "label": "Description", "type": "text",
                 "labels": ["description", "item", "descricao"]},
                {"key": "quantity", "label": "Qty", "type": "number",
                 "labels": ["qty", "quantity", "quantidade"]},
                {"key": "unit_price", "label": "Unit price", "type": "money",
                 "labels": ["unit price", "price", "preco unitario"]},
                {"key": "amount", "label": "Amount", "type": "money",
                 "labels": ["amount", "line total", "valor"]},
            ],
        },
    },
    {
        "id": "inspection-report",
        "name": "Inspection report",
        "description": "Equipment or site inspection with a result.",
        "keywords": ["inspection", "inspection report", "relatorio de inspecao", "checklist"],
        "fields": [
            _f("report_id", "Report ID", "identifier", ["report id", "report", "relatorio"],
               pattern=r"^[A-Z]{2,5}-\d{3,8}$"),
            _f("site", "Site", "text", ["site", "location", "local"]),
            _f("inspector", "Inspector", "text", ["inspector", "inspected by", "inspetor"]),
            _f("date", "Inspection date", "date", ["date", "inspection date", "data"]),
            _f("result", "Result", "enum", ["result", "outcome", "resultado"],
               options=["pass", "fail", "conditional"]),
            _f("readings", "Readings", "number", ["reading", "readings", "measurement"],
               required=False),
            _f("notes", "Notes", "text", ["notes", "remarks", "observacoes"], required=False),
        ],
    },
    {
        "id": "administrative-request",
        "name": "Administrative request",
        "description": "Internal request routed to a department.",
        "keywords": ["request", "protocol", "requerimento", "protocolo", "department"],
        "fields": [
            _f("protocol", "Protocol", "identifier", ["protocol", "protocolo", "request id"],
               pattern=r"^[A-Z]{2,5}-\d{3,8}$"),
            _f("requester", "Requester", "text", ["requester", "applicant", "requerente"]),
            _f("department", "Department", "text", ["department", "setor", "departamento"]),
            _f("date", "Date", "date", ["date", "data"]),
            _f("subject", "Subject", "text", ["subject", "assunto"]),
        ],
    },
]


def validate_definition(d: dict) -> dict:
    """Return a normalised template definition or raise ValueError."""
    if not isinstance(d, dict):
        raise ValueError("Template must be an object")
    allowed = {"id", "name", "description", "keywords", "fields", "table"}
    if set(d) - allowed:
        raise ValueError(f"Unknown template keys: {sorted(set(d) - allowed)}")
    tid = d.get("id", "")
    if not isinstance(tid, str) or not SLUG.match(tid):
        raise ValueError("Template id must be 2-40 lowercase letters, digits or hyphens")
    name = d.get("name", "")
    if not isinstance(name, str) or not (1 <= len(name.strip()) <= 80):
        raise ValueError("Template name must be 1-80 characters")
    keywords = d.get("keywords", [])
    if not isinstance(keywords, list) or len(keywords) > 30 or not all(
        isinstance(k, str) and 1 <= len(k.strip()) <= 60 for k in keywords
    ):
        raise ValueError("Keywords: up to 30 entries of 1-60 characters")
    fields = d.get("fields")
    if not isinstance(fields, list) or not (1 <= len(fields) <= 30):
        raise ValueError("A template needs 1-30 fields")
    seen = set()
    clean_fields = [_validate_field(f, seen) for f in fields]
    table = d.get("table")
    if table is not None:
        if not isinstance(table, dict) or not SLUG.match(str(table.get("key", "")).replace("_", "-")):
            raise ValueError("Table needs a key")
        cols = table.get("columns")
        if not isinstance(cols, list) or not (2 <= len(cols) <= 12):
            raise ValueError("A table needs 2-12 columns")
        col_seen: set = set()
        table = {
            "key": table["key"],
            "label": str(table.get("label") or table["key"])[:80],
            "columns": [_validate_field({**c, "required": False}, col_seen) for c in cols],
        }
    out = {
        "id": tid,
        "name": name.strip(),
        "description": str(d.get("description", ""))[:300],
        "keywords": [k.strip().lower() for k in keywords],
        "fields": clean_fields,
    }
    if table:
        out["table"] = table
    return out


def _validate_field(f: dict, seen: set) -> dict:
    if not isinstance(f, dict):
        raise ValueError("Field must be an object")
    key = f.get("key", "")
    if not isinstance(key, str) or not re.match(r"^[a-z][a-z0-9_]{0,39}$", key) or key in seen:
        raise ValueError(f"Invalid or duplicate field key: {key!r}")
    seen.add(key)
    type_ = f.get("type", "text")
    if type_ not in FIELD_TYPES:
        raise ValueError(f"Field {key}: type must be one of {sorted(FIELD_TYPES)}")
    labels = f.get("labels") or [key.replace("_", " ")]
    if not isinstance(labels, list) or not (1 <= len(labels) <= 20) or not all(
        isinstance(x, str) and 1 <= len(x.strip()) <= 60 for x in labels
    ):
        raise ValueError(f"Field {key}: 1-20 labels of 1-60 characters")
    out = {
        "key": key,
        "label": str(f.get("label") or key.replace("_", " ").title())[:80],
        "type": type_,
        "labels": [x.strip().lower() for x in labels],
        "required": bool(f.get("required", True)),
    }
    pattern = f.get("pattern")
    if pattern:
        if not isinstance(pattern, str) or len(pattern) > 200:
            raise ValueError(f"Field {key}: pattern must be at most 200 characters")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Field {key}: invalid pattern ({exc})") from None
        out["pattern"] = pattern
    if type_ == "enum":
        options = f.get("options")
        if not isinstance(options, list) or not (1 <= len(options) <= 50) or not all(
            isinstance(o, str) and 1 <= len(o) <= 60 for o in options
        ):
            raise ValueError(f"Field {key}: enum needs 1-50 options")
        out["options"] = options
    return out


class Templates:
    def __init__(self, db: Database):
        self.db = db
        with db.connect(immediate=True) as c:
            for t in BUILTIN:
                definition = json.dumps(validate_definition(t))
                c.execute(
                    "INSERT INTO templates(id,name,definition,builtin,created,updated) "
                    "VALUES(?,?,?,1,?,?) ON CONFLICT(id) DO UPDATE SET "
                    "definition=excluded.definition, name=excluded.name WHERE builtin=1",
                    (t["id"], t["name"], definition, now(), now()),
                )

    def all(self) -> list[dict]:
        with self.db.connect() as c:
            rows = c.execute("SELECT * FROM templates ORDER BY builtin DESC, name").fetchall()
        return [{**json.loads(r["definition"]), "builtin": bool(r["builtin"])} for r in rows]

    def get(self, tid: str) -> dict:
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM templates WHERE id=?", (tid,)).fetchone()
        if not row:
            raise KeyError(tid)
        return {**json.loads(row["definition"]), "builtin": bool(row["builtin"])}

    def save(self, definition: dict, actor: str) -> dict:
        clean = validate_definition(definition)
        with self.db.connect(immediate=True) as c:
            row = c.execute("SELECT builtin FROM templates WHERE id=?", (clean["id"],)).fetchone()
            if row and row["builtin"]:
                raise PermissionError("Built-in templates are read-only; save a copy with a new id")
            c.execute(
                "INSERT INTO templates(id,name,definition,builtin,created,updated) VALUES(?,?,?,0,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, definition=excluded.definition, "
                "updated=excluded.updated",
                (clean["id"], clean["name"], json.dumps(clean), now(), now()),
            )
            audit(c, None, "template.saved", actor, {"template": clean["id"], "fields": len(clean["fields"])})
        return clean

    def delete(self, tid: str, actor: str) -> None:
        with self.db.connect(immediate=True) as c:
            row = c.execute("SELECT builtin FROM templates WHERE id=?", (tid,)).fetchone()
            if not row:
                raise KeyError(tid)
            if row["builtin"]:
                raise PermissionError("Built-in templates cannot be deleted")
            used = c.execute("SELECT COUNT(*) FROM documents WHERE template_id=?", (tid,)).fetchone()[0]
            if used:
                raise PermissionError(f"Template is used by {used} document(s)")
            c.execute("DELETE FROM templates WHERE id=?", (tid,))
            audit(c, None, "template.deleted", actor, {"template": tid})
