"""Local extraction. Model scores are never reported as field accuracy."""

import io
import re
import threading
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

MAX_BYTES = 10 * 1024 * 1024
MAX_TEXT = 200_000
Image.MAX_IMAGE_PIXELS = 12_000_000
_engine = None
_ocr_lock = threading.Lock()


@dataclass
class Result:
    text: str
    method: str
    fields: dict


def media_type(data: bytes) -> str:
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Empty document or document exceeds 10 MiB")
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if b"\x00" in data:
        raise ValueError("Unsupported document signature")
    try:
        value = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Only UTF-8 text, PNG, JPEG and native-text PDF are supported") from exc
    if len(value) > MAX_TEXT or any(ord(c) < 32 and c not in "\n\r\t" for c in value):
        raise ValueError("Invalid text document")
    return "text/plain"


def fields_from_text(text: str) -> dict:
    fields = {}
    for key, pattern in {
        "reference": r"^(?:reference|referencia)\s*:\s*(.+)$",
        "organization": r"^(?:organization|organizacao)\s*:\s*(.+)$",
        "category": r"^(?:category|categoria)\s*:\s*(.+)$",
        "date": r"^(?:date|data)\s*:\s*(.+)$",
        "description": r"^(?:description|descricao)\s*:\s*(.+)$",
    }.items():
        matches = list(re.finditer(pattern, text, re.I | re.M))
        value = matches[0].group(1).strip()[:1000] if matches else ""
        fields[key] = {
            "value": value,
            "evidence": matches[0].group(0)[:1200] if matches else "",
            "ambiguous": len(matches) > 1,
            "confidence": None,
        }
    return fields


def extract(data: bytes, mime: str) -> Result:
    global _engine
    if mime == "text/plain":
        text = data.decode("utf-8-sig")
        method = "native-text"
    elif mime == "application/pdf":
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or len(reader.pages) > 30:
            raise ValueError("PDF must be unencrypted and contain at most 30 pages")
        chunks = []
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
            if sum(map(len, chunks)) > MAX_TEXT:
                raise ValueError("PDF text exceeds processing limit")
        text = "\n".join(chunks)
        if not text.strip():
            raise ValueError("Scanned PDF: export pages to PNG/JPEG for local OCR")
        method = "pdf-native"
    else:
        try:
            with Image.open(io.BytesIO(data)) as im:
                if im.width * im.height > 12_000_000:
                    raise ValueError("Image exceeds 12 megapixels")
                im.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValueError("Invalid image") from exc
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise ValueError("Local OCR unavailable. Install requirements-ocr.txt") from exc
        import numpy as np

        with _ocr_lock:
            if _engine is None:
                _engine = RapidOCR()
            with Image.open(io.BytesIO(data)) as im:
                lines, _ = _engine(np.array(im.convert("RGB")))
        text = "\n".join(line[1] for line in lines or [])
        if not text.strip():
            raise ValueError("OCR found no text; review image quality")
        method = "rapidocr-local"
    if len(text) > MAX_TEXT:
        raise ValueError("Extracted text exceeds limit")
    return Result(text, method, fields_from_text(text))
