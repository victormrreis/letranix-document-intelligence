"""Synthetic fixtures generated from literal, invented content. Never reads an operational source."""

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BANNER = "SYNTHETIC DEMONSTRATION - NOT AN OPERATIONAL DOCUMENT"


def native_pdf(pages: list[list[str]] | list[str], font: str = "Helvetica") -> bytes:
    """Minimal text PDF writer (one Tj per line) so fixtures need no PDF library."""
    if pages and isinstance(pages[0], str):
        pages = [pages]
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids = []
    font_id = 3
    objects.append(f"<< /Type /Font /Subtype /Type1 /BaseFont /{font} >>".encode())
    for lines in pages:
        text = "BT /F1 11 Tf 50 780 Td 16 TL\n"
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            text += f"({escaped}) Tj T*\n"
        stream = (text + "ET").encode("latin-1")
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        content_id = len(objects)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode()
        )
        kids.append(len(objects))
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    result = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(result)
    result += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    result += b"".join(f"{n:010d} 00000 n \n".encode() for n in offsets)
    result += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    return result


def font(size: int, handwriting: bool = False):
    # Operating-system fonts are only rendered into pixels; no font file is redistributed.
    candidates = (["C:/Windows/Fonts/segoepr.ttf"] if handwriting else []) + [
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def render(lines, size=(1700, 1100), text_size=34, handwriting=False, layout=None) -> Image.Image:
    """Render lines (or (x, y, text) tuples when ``layout`` is given) onto a page."""
    im = Image.new("RGB", size, "#fbfaf6")
    draw = ImageDraw.Draw(im)
    f = font(text_size, handwriting)
    draw.rectangle((24, 24, size[0] - 24, size[1] - 24), outline="#b9bec6", width=2)
    if layout:
        for x, y, text in layout:
            draw.text((x, y), text, font=f, fill="#1b2a41")
    else:
        for i, line in enumerate(lines):
            draw.text((60, 60 + i * int(text_size * 1.9)), line, font=f, fill="#1b2a41")
    return im


SERVICE_ORDER = [
    BANNER,
    "SERVICE ORDER",
    "Order No.: SO-10423",
    "Requested by: Ana Exemplo",
    "Location: Fictional Building 7",
    "Date: 15/03/2026",
    "Due date: 2026-03-29",
    "Priority: High",
    "Description: Replace the fictional air filter in room 12.",
]

INVOICE = [
    BANNER,
    "INVOICE",
    "Invoice No.: INV-2087",
    "Issuer: Example Works Lab",
    "Bill to: Sample Trading Co.",
    "Issue date: 02 Apr 2026",
    "Due date: 2026-05-02",
    "",
    "Description            Qty    Unit price    Amount",
    "Archive labels          10          2.50     25.00",
    "Scanner calibration      1        180.00    180.00",
    "Document boxes           4         12.25     49.00",
    "",
    "Total: $254.00",
]

INSPECTION = [
    BANNER,
    "INSPECTION REPORT",
    "Report ID: IR-3310",
    "Site: Demo Plant North",
    "Inspector: Bruno Ficticio",
    "Date: 2026-02-20",
    "Result: Pass",
    "Notes: Synthetic pressure gauge within range.",
]

REQUEST_P1 = [
    BANNER,
    "ADMINISTRATIVE REQUEST",
    "Protocol: AR-5521",
    "Requester: Carla Modelo",
    "Department: Records Office",
    "Date: 10/01/2026",
]
REQUEST_P2 = [
    "Page 2 of 2",
    "Subject: Access to the fictional archive room",
    "Justification: quarterly synthetic audit.",
]

FORM_LAYOUT = [
    (60, 60, BANNER),
    (60, 140, "SERVICE ORDER - FIELD FORM"),
    (60, 240, "Order number"), (60, 300, "SO-20981"),
    (760, 240, "Priority"), (760, 300, "Urgent"),
    (60, 420, "Requester"), (60, 480, "Diego Amostra"),
    (760, 420, "Date"), (760, 480, "2026-06-05"),
    (60, 600, "Description"), (60, 660, "Inspect the sample conveyor belt."),
]


def generate(destination: Path) -> list[str]:
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "service-order.txt").write_text("\n".join(SERVICE_ORDER) + "\n", encoding="utf-8", newline="\n")
    (destination / "invoice.pdf").write_bytes(native_pdf(INVOICE, font="Courier"))

    report = render(INSPECTION).rotate(2.0, resample=Image.BICUBIC, expand=True, fillcolor="#fbfaf6")
    report.save(destination / "inspection-report.png")

    pages = [render(REQUEST_P1).convert("L"), render(REQUEST_P2).convert("L")]
    pages[0].save(destination / "scanned-request.pdf", save_all=True, append_images=pages[1:], resolution=150)

    form = render([], size=(1500, 780), layout=FORM_LAYOUT)
    form = form.resize((1050, 546)).filter(ImageFilter.GaussianBlur(0.6)).rotate(90, expand=True)
    form.save(destination / "rotated-field-form.jpg", quality=60)

    handwriting = render([BANNER, "Request: AR-7730", "Requester: Example Operator A",
                          "Department: Sample Library", "Date: 2026-01-15", "Subject: Request sample forms"],
                         text_size=30, handwriting=True)
    handwriting.save(destination / "handwritten-style-request.png")

    manifest = {
        "provenance": "Created from literal invented content by letranix.demo; no source documents",
        "handwriting_note": "Rendered handwriting-style font when available; not human handwriting.",
        "files": {},
    }
    names = sorted(p.name for p in destination.iterdir() if p.name != "manifest.json")
    for name in names:
        manifest["files"][name] = hashlib.sha256((destination / name).read_bytes()).hexdigest()
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return names


def seed(data: Path, fixtures: Path) -> int:
    """Import fixtures through the normal import path (dedup, audit, auto-processing)."""
    from .service import Letranix

    names = generate(fixtures)
    svc = Letranix(data, start_workers=False)
    try:
        imported = 0
        for name in names:
            r = svc.import_bytes(name, (fixtures / name).read_bytes(), "demo-generator", via="demo")
            imported += not r["duplicate"]
        while svc.run_next_job():
            pass
        return imported
    finally:
        svc.close()
