"""Typed, validated workspace settings persisted in SQLite.

Every setting is declared here with its type and bounds; values outside the
declaration are rejected before they are stored, so a malformed request cannot
switch off limits or point the integration at an arbitrary host.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .db import Database, now


@dataclass(frozen=True)
class Spec:
    default: object
    kind: str  # bool | int | float | choice | text | loopback-url | directory
    label: str
    group: str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple = ()
    help: str = ""


SPECS: dict[str, Spec] = {
    "processing.auto_process": Spec(
        True, "bool", "Process automatically after import", "processing",
        help="Queue extraction as soon as a document is imported.",
    ),
    "processing.max_file_mb": Spec(10, "int", "Maximum file size (MiB)", "processing", 1, 50),
    "processing.max_pages": Spec(30, "int", "Maximum pages per document", "processing", 1, 200),
    "processing.inbox_dir": Spec(
        "", "directory", "Inbox folder", "processing",
        help="Absolute folder scanned on demand by 'Import from inbox'. Not recursive.",
    ),
    "ocr.engine": Spec(
        "rapidocr", "choice", "OCR engine", "ocr", choices=("rapidocr", "none"),
        help="'none' disables image OCR; native PDF/text extraction keeps working.",
    ),
    "ocr.render_dpi": Spec(200, "int", "Scanned PDF render resolution (DPI)", "ocr", 100, 300),
    "ocr.prefer_native_pdf_text": Spec(
        True, "bool", "Use embedded PDF text when present", "ocr",
        help="Pages with fewer than 20 embedded characters are rendered and OCRed.",
    ),
    "ocr.auto_orientation": Spec(
        True, "bool", "Detect rotated pages", "ocr",
        help="Retries poorly recognised pages at 90/180/270 degrees.",
    ),
    "ocr.preprocess.grayscale": Spec(True, "bool", "Grayscale", "ocr"),
    "ocr.preprocess.autocontrast": Spec(True, "bool", "Auto contrast", "ocr"),
    "ocr.preprocess.denoise": Spec(True, "bool", "Median denoise", "ocr"),
    "ocr.preprocess.deskew": Spec(True, "bool", "Deskew", "ocr"),
    "ocr.preprocess.upscale": Spec(True, "bool", "Upscale small scans", "ocr"),
    "ocr.min_line_score": Spec(
        0.6, "float", "Low-confidence threshold", "ocr", 0.0, 1.0,
        help="OCR lines whose engine recognition score is below this are flagged in review.",
    ),
    "review.require_approval_reason": Spec(True, "bool", "Require a reason to approve", "review"),
    "review.default_reviewer": Spec("Demo Reviewer", "text", "Default reviewer label", "review"),
    "learning.enabled": Spec(True, "bool", "Apply learned rules", "learning"),
    "learning.min_support": Spec(
        2, "int", "Confirmations before a rule activates", "learning", 1, 20,
    ),
    "integration.adapter": Spec(
        "local-ledger", "choice", "Destination", "integration",
        choices=("local-ledger", "http-demo"),
    ),
    "integration.endpoint": Spec(
        "http://127.0.0.1:8797/records", "loopback-url", "Demo destination endpoint", "integration",
        help="Loopback HTTP only. Start it with: python -m letranix mock-destination",
    ),
    "integration.max_attempts": Spec(5, "int", "Delivery attempts", "integration", 1, 10),
    "ui.theme": Spec("system", "choice", "Theme", "interface", choices=("system", "light", "dark")),
    "ui.density": Spec(
        "comfortable", "choice", "Density", "interface", choices=("comfortable", "compact"),
    ),
}


def validate(key: str, value):
    spec = SPECS.get(key)
    if spec is None:
        raise ValueError(f"Unknown setting: {key}")
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if spec.kind in {"int", "float"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be a number")
        if spec.kind == "int" and int(value) != value:
            raise ValueError(f"{key} must be a whole number")
        if not (spec.minimum <= value <= spec.maximum):
            raise ValueError(f"{key} must be between {spec.minimum:g} and {spec.maximum:g}")
        return int(value) if spec.kind == "int" else float(value)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    value = value.strip()
    if spec.kind == "choice":
        if value not in spec.choices:
            raise ValueError(f"{key} must be one of: {', '.join(spec.choices)}")
        return value
    if spec.kind == "text":
        if not (1 <= len(value) <= 80) or not value.isprintable():
            raise ValueError(f"{key} must be 1-80 printable characters")
        return value
    if spec.kind == "loopback-url":
        parts = urlsplit(value)
        if (
            parts.scheme != "http"
            or parts.hostname not in {"127.0.0.1", "localhost"}
            or parts.username
            or parts.password
            or len(value) > 200
        ):
            raise ValueError("The demonstration endpoint must be an http://127.0.0.1 URL")
        try:
            parts.port
        except ValueError as exc:
            raise ValueError("Invalid port") from exc
        return value
    if spec.kind == "directory":
        if value == "":
            return value
        path = Path(value)
        if not path.is_absolute() or len(value) > 400 or re.match(r"^\\\\", value):
            raise ValueError("Inbox must be an absolute local folder (network shares not allowed)")
        if not path.is_dir():
            raise ValueError("Inbox folder does not exist")
        return str(path.resolve())
    raise ValueError(f"Unsupported setting type for {key}")


class Settings:
    def __init__(self, db: Database):
        self.db = db

    def all(self) -> dict:
        with self.db.connect() as c:
            stored = {r["key"]: json.loads(r["value"]) for r in c.execute("SELECT * FROM settings")}
        values = {}
        for key, spec in SPECS.items():
            value = stored.get(key, spec.default)
            try:
                values[key] = validate(key, value)
            except ValueError:
                values[key] = spec.default  # e.g. inbox folder deleted since it was saved.
        return values

    def get(self, key: str):
        return self.all()[key]

    def update(self, changes: dict) -> list[str]:
        clean = {k: validate(k, v) for k, v in changes.items()}  # Validate all before writing.
        with self.db.connect(immediate=True) as c:
            for key, value in clean.items():
                c.execute(
                    "INSERT INTO settings(key,value,updated) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                    (key, json.dumps(value), now()),
                )
        return sorted(clean)

    @staticmethod
    def schema() -> list[dict]:
        return [
            {
                "key": key,
                "default": s.default,
                "kind": s.kind,
                "label": s.label,
                "group": s.group,
                "minimum": s.minimum,
                "maximum": s.maximum,
                "choices": list(s.choices),
                "help": s.help,
            }
            for key, s in SPECS.items()
        ]
