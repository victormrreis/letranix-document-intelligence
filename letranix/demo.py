"""Generate fixtures from literal, invented content. Never read an operational source."""

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .processing import extract, media_type
from .store import Store, now, uid


def native_pdf(lines: list[str]) -> bytes:
    text = "BT /F1 14 Tf 50 770 Td 22 TL\n"
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        text += f"({escaped}) Tj T*\n"
    text += "ET"
    stream = text.encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    result = b"%PDF-1.4\n"
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(result)
    result += b"xref\n0 6\n0000000000 65535 f \n"
    result += b"".join(f"{n:010d} 00000 n \n".encode() for n in offsets[1:])
    result += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    return result


def generate(destination: Path):
    destination.mkdir(parents=True, exist_ok=True)
    base = [
        "SYNTHETIC DEMONSTRATION - NOT AN OPERATIONAL DOCUMENT",
        "Organization: Example Works Lab",
        "Date: 2026-01-15",
    ]
    examples = {
        "service-order.txt": base
        + [
            "Reference: DEMO-001",
            "Category: service-order",
            "Description: Inspect the fictional document scanner.",
        ],
        "operational-report.png": base
        + [
            "Reference: DEMO-002",
            "Category: operational-report",
            "Description: Synthetic equipment inspection completed.",
        ],
        "administrative-request.pdf": base
        + [
            "Reference: DEMO-003",
            "Category: administrative-request",
            "Description: Request fictional archive labels.",
        ],
        "low-quality-scan.jpg": base
        + [
            "Reference: DEMO-004",
            "Category: operational-report",
            "Description: Artificially degraded synthetic scan.",
        ],
        "handwritten-form.png": base
        + [
            "Reference: DEMO-005",
            "Category: handwritten-form",
            "Description: Example Operator A requests sample forms.",
        ],
    }
    manifest = {
        "provenance": "Created from literal invented content by letranix.demo; no source documents",
        "files": {},
    }
    for name, lines in examples.items():
        p = destination / name
        if p.suffix == ".txt":
            p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        elif p.suffix == ".pdf":
            p.write_bytes(native_pdf(lines))
        else:
            im = Image.new("RGB", (1600, 650), "#faf9f5")
            draw = ImageDraw.Draw(im)
            # OS font is rendered only; no font file is copied or redistributed.
            font_path = Path("C:/Windows/Fonts/segoepr.ttf")
            handwritten = name == "handwritten-form.png" and font_path.is_file()
            printed_font = Path("C:/Windows/Fonts/arial.ttf")
            if handwritten:
                font = ImageFont.truetype(str(font_path), 27)
            elif printed_font.is_file():
                font = ImageFont.truetype(str(printed_font), 32)
            else:
                font = ImageFont.load_default(size=32)
            draw.rectangle((25, 25, 1575, 625), outline="#c3c7cd", width=2)
            for i, line in enumerate(lines):
                draw.text((52, 65 + i * 72), line, font=font, fill="#182a43")
            if name == "low-quality-scan.jpg":
                im = im.resize((1000, 406)).filter(ImageFilter.GaussianBlur(0.5))
                im.save(p, quality=55)
            else:
                im.save(p)
            if name == "handwritten-form.png":
                manifest["handwriting_note"] = (
                    "Rendered handwriting-style font; not human handwriting. OCR handwriting support is experimental."
                    if handwritten
                    else "Fallback printed font; handwriting-style font unavailable on this host."
                )
        manifest["files"][name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return list(examples)


def seed(data: Path, fixtures: Path):
    names = generate(fixtures)
    store = Store(data)
    count = 0
    for name in names:
        raw = (fixtures / name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with store.connect() as c:
            if c.execute("SELECT 1 FROM documents WHERE digest=?", (digest,)).fetchone():
                continue
            doc_id = uid()
            mime = media_type(raw)
            (store.files / doc_id).write_bytes(raw)
            c.execute(
                "INSERT INTO documents(id,name,mime,digest,created,status) VALUES(?,?,?,?,?,?)",
                (doc_id, name, mime, digest, now(), "imported"),
            )
            store.audit(
                c, doc_id, "demo.synthetic-import", "demo-generator", {"generator": "letranix.demo"}
            )
            if mime in {"text/plain", "application/pdf"}:
                result = extract(raw, mime)
                c.execute(
                    "UPDATE documents SET status='needs-review',version=1,text=?,method=?,fields=? WHERE id=?",
                    (result.text, result.method, json.dumps(result.fields), doc_id),
                )
                c.execute(
                    "INSERT INTO jobs(id,document_id,state,created) VALUES(?,?,?,?)",
                    (uid(), doc_id, "done", now()),
                )
                store.audit(c, doc_id, "processing.completed", "system", {"method": result.method})
        count += 1
    return count
