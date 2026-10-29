"""Format detection, page loading, image preprocessing and local OCR.

Nothing here contacts a network service. RapidOCR (ONNX Runtime) is optional;
without it, native text and PDF extraction keep working and image OCR fails with
an explicit message.
"""

import io
import re
import threading
import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

MAX_TEXT = 400_000
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
NATIVE_MIN_CHARS = 20

_engine = None
_engine_lock = threading.Lock()


class DocumentError(ValueError):
    """A user-facing problem with the document itself (not an internal fault)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Cancelled(Exception):
    pass


SIGNATURES = [
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
]
EXTENSIONS = {
    "application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg",
    "image/tiff": ".tif", "image/webp": ".webp", "text/plain": ".txt",
}


def media_type(data: bytes, max_bytes: int) -> str:
    """Identify the format from content, never from the file name."""
    if not data:
        raise DocumentError("empty", "The document is empty")
    if len(data) > max_bytes:
        raise DocumentError("too-large", f"Document exceeds {max_bytes // (1024 * 1024)} MiB")
    for prefix, mime in SIGNATURES:
        if data.startswith(prefix):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if b"\x00" in data[:4096]:
        raise DocumentError("unsupported", "Unsupported file type")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentError(
            "unsupported", "Supported: PDF, PNG, JPEG, TIFF, WebP and UTF-8 text"
        ) from None
    if len(text) > MAX_TEXT or any(ord(ch) < 32 and ch not in "\n\r\t\f" for ch in text):
        raise DocumentError("invalid-text", "Text file contains control characters or is too long")
    return "text/plain"


@dataclass
class PageInput:
    number: int
    text: str | None = None  # Native text, when available.
    image: Image.Image | None = None  # Rendered/decoded image needing OCR.
    source: str = ""


@dataclass
class PageResult:
    number: int
    method: str
    text: str
    rows: list = field(default_factory=list)
    width: int = 0
    height: int = 0
    mean_score: float | None = None
    steps: list = field(default_factory=list)
    image: Image.Image | None = None
    ms: int = 0


def count_pages(data: bytes, mime: str) -> int:
    if mime == "application/pdf":
        return len(_pdf_reader(data).pages)
    if mime.startswith("image/"):
        with _open_image(data) as im:
            frames = getattr(im, "n_frames", 1)
            try:
                im.load()  # Decode the first frame now so truncated files fail at import.
            except (OSError, ValueError, SyntaxError) as exc:
                raise DocumentError("corrupted", "The image is damaged or truncated") from exc
            return frames
    return 1


def _pdf_reader(data: bytes):
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise DocumentError("encrypted", "Encrypted PDFs are not supported")
        _ = len(reader.pages)
        return reader
    except DocumentError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, IndexError, OSError) as exc:
        raise DocumentError("corrupted", "The PDF is damaged or not a valid PDF") from exc


def _open_image(data: bytes) -> Image.Image:
    try:
        im = Image.open(io.BytesIO(data))
        if im.width * im.height > MAX_PIXELS:
            raise DocumentError("too-large", "Image exceeds 40 megapixels")
        return im
    except DocumentError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise DocumentError("corrupted", "The image is damaged or unreadable") from exc


def iter_pages(data: bytes, mime: str, *, dpi: int, prefer_native: bool, max_pages: int):
    """Yield one PageInput at a time so callers can report progress and cancel."""
    if mime == "text/plain":
        yield PageInput(1, text=data.decode("utf-8-sig"), source="native-text")
        return
    if mime == "application/pdf":
        reader = _pdf_reader(data)
        total = len(reader.pages)
        if total == 0:
            raise DocumentError("empty", "The PDF has no pages")
        if total > max_pages:
            raise DocumentError("too-many-pages", f"PDF has {total} pages; limit is {max_pages}")
        pdfium = None
        for index, page in enumerate(reader.pages):
            try:
                native = page.extract_text() or ""
            except Exception:  # Damaged content stream on one page: fall back to rendering.
                native = ""
            if prefer_native and len(native.strip()) >= NATIVE_MIN_CHARS:
                yield PageInput(index + 1, text=native, source="pdf-native")
                continue
            if pdfium is None:
                pdfium = _open_pdfium(data)
            yield PageInput(index + 1, image=render_pdf_page(pdfium, index, dpi), source="pdf-render")
        return
    im = _open_image(data)
    frames = getattr(im, "n_frames", 1)
    if frames > max_pages:
        raise DocumentError("too-many-pages", f"Image has {frames} frames; limit is {max_pages}")
    for index in range(frames):
        try:
            im.seek(index)
            frame = ImageOps.exif_transpose(im.copy()).convert("RGB")
        except (OSError, ValueError, SyntaxError) as exc:
            raise DocumentError("corrupted", "The image is damaged or truncated") from exc
        yield PageInput(index + 1, image=frame, source="image")


def _open_pdfium(data: bytes):
    import pypdfium2 as pdfium

    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise DocumentError("corrupted", "The PDF cannot be rendered") from exc


def render_pdf_page(pdf, index: int, dpi: int) -> Image.Image:
    page = pdf[index]
    width, height = page.get_size()
    scale = dpi / 72
    if width * height * scale * scale > MAX_PIXELS:
        scale = (MAX_PIXELS / (width * height)) ** 0.5
    return page.render(scale=scale).to_pil().convert("RGB")


def render_preview(data: bytes, page_number: int, dpi: int = 110) -> Image.Image:
    pdf = _open_pdfium(data)
    if not 1 <= page_number <= len(pdf):
        raise DocumentError("page", "Page out of range")
    return render_pdf_page(pdf, page_number - 1, dpi)


# --- Preprocessing -----------------------------------------------------------


def estimate_skew(gray: Image.Image, limit: float = 6.0, step: float = 0.5) -> float:
    """Projection-profile skew estimate in degrees (positive = counter-clockwise)."""
    small = gray.copy()
    small.thumbnail((900, 900))
    arr = np.asarray(small, dtype=np.uint8)
    threshold = arr.mean() - arr.std() * 0.5
    ink = Image.fromarray(((arr < threshold) * 255).astype(np.uint8))
    best, best_score = 0.0, -1.0
    for angle in np.arange(-limit, limit + step / 2, step):
        rotated = np.asarray(ink.rotate(float(angle), resample=Image.NEAREST, fillcolor=0))
        profile = rotated.sum(axis=1, dtype=np.float64)
        score = float(np.var(profile))
        if score > best_score:
            best, best_score = float(angle), score
    return best


def preprocess(image: Image.Image, options: dict) -> tuple[Image.Image, list[str]]:
    steps = []
    out = image
    if options.get("upscale"):
        width = out.width
        if width < 1400:
            factor = min(2.5, 1600 / width)
            out = out.resize((round(out.width * factor), round(out.height * factor)), Image.LANCZOS)
            steps.append(f"upscale x{factor:.2f}")
    if options.get("grayscale"):
        out = ImageOps.grayscale(out)
        steps.append("grayscale")
    if options.get("denoise"):
        out = out.filter(ImageFilter.MedianFilter(3))
        steps.append("median-denoise")
    if options.get("autocontrast"):
        out = ImageOps.autocontrast(out if out.mode == "L" else out.convert("RGB"), cutoff=1)
        steps.append("autocontrast")
    if options.get("deskew"):
        angle = estimate_skew(ImageOps.grayscale(out))
        if abs(angle) >= 0.5:
            fill = 255 if out.mode == "L" else (255, 255, 255)
            out = out.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=fill)
            steps.append(f"deskew {angle:+.1f}deg")
    return out.convert("RGB"), steps


# --- OCR ---------------------------------------------------------------------


def engine_available(name: str) -> bool:
    if name == "rapidocr":
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            return False
        return True
    return name == "none"


def _rapidocr():
    global _engine
    if _engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            raise DocumentError(
                "ocr-unavailable", "Local OCR engine not installed (pip install -r requirements-ocr.txt)"
            ) from None
        _engine = RapidOCR()
    return _engine


CAMEL = re.compile(r"(?<=[a-zà-ÿ])(?=[A-ZÀ-Þ][a-zà-ÿ])")


def respace(text: str) -> str:
    """Restore a dropped space at a lowercase-to-Capitalised boundary ("CarlaModelo").

    The PP-OCR recogniser sometimes omits spaces on large text. Per-character
    boxes proved too noisy to locate word gaps reliably (measured: intra-word
    gaps as wide as real ones), so only this unambiguous case is repaired.
    Lowercase run-ons ("sampleforms") are left for the reviewer.
    """
    return CAMEL.sub(" ", text)


def recognize(image: Image.Image) -> list[dict]:
    """Return text segments with axis-aligned boxes and the engine's recognition score."""
    with _engine_lock:
        result, _ = _rapidocr()(np.asarray(image.convert("RGB")))
    segments = []
    for box, text, score in result or []:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        text = respace(str(text).strip())
        if text:
            segments.append(
                {
                    "text": text,
                    "bbox": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))],
                    "score": round(float(score), 4),
                }
            )
    return segments


def _vertical_share(segments: list[dict]) -> float:
    """Share of multi-character segments whose box is much taller than wide."""
    long = [s for s in segments if len(s["text"]) >= 4]
    if not long:
        return 0.0
    tall = [s for s in long if (s["bbox"][3] - s["bbox"][1]) > 1.5 * (s["bbox"][2] - s["bbox"][0])]
    return len(tall) / len(long)


def group_rows(segments: list[dict]) -> list[dict]:
    """Group segments into reading-order rows by vertical overlap."""
    rows: list[dict] = []
    for seg in sorted(segments, key=lambda s: ((s["bbox"][1] + s["bbox"][3]) / 2, s["bbox"][0])):
        y0, y1 = seg["bbox"][1], seg["bbox"][3]
        placed = False
        for row in rows[-3:]:
            r0, r1 = row["bbox"][1], row["bbox"][3]
            overlap = min(y1, r1) - max(y0, r0)
            if overlap > 0.5 * min(y1 - y0, r1 - r0):
                row["segments"].append(seg)
                row["bbox"] = [
                    min(row["bbox"][0], seg["bbox"][0]), min(r0, y0),
                    max(row["bbox"][2], seg["bbox"][2]), max(r1, y1),
                ]
                placed = True
                break
        if not placed:
            rows.append({"segments": [seg], "bbox": list(seg["bbox"])})
    rows.sort(key=lambda r: r["bbox"][1])
    for row in rows:
        row["segments"].sort(key=lambda s: s["bbox"][0])
        row["text"] = " ".join(s["text"] for s in row["segments"])
        row["score"] = round(min(s["score"] for s in row["segments"]), 4)
    return rows


def _quality(segments: list[dict]) -> float:
    return sum(s["score"] * len(s["text"]) for s in segments)


def ocr_page(page: PageInput, options: dict) -> PageResult:
    started = time.perf_counter()
    image, steps = preprocess(page.image, options)
    segments = recognize(image)
    chars = sum(len(s["text"]) for s in segments)
    mean = (sum(s["score"] for s in segments) / len(segments)) if segments else 0.0
    rotated_page = _vertical_share(segments) > 0.5
    if options.get("auto_orientation") and (rotated_page or chars < 15 or mean < 0.6):
        # Vertical boxes mean a page turned 90 degrees: the recogniser can still read the
        # crops, but reading order and layout are lost, so the page itself is rotated.
        best = (-1.0 if rotated_page else _quality(segments), 0, image, segments)
        for angle in (90, 270) if rotated_page else (90, 270, 180):
            turned = image.rotate(angle, expand=True, fillcolor=(255, 255, 255))
            candidate = recognize(turned)
            if _vertical_share(candidate) <= 0.5 and _quality(candidate) > best[0] * 1.2:
                best = (_quality(candidate), angle, turned, candidate)
        if best[1]:
            image, segments = best[2], best[3]
            steps.append(f"rotate {best[1]}deg")
    rows = group_rows(segments)
    scores = [s["score"] for s in segments]
    return PageResult(
        number=page.number,
        method="ocr-rapidocr" + ("-pdf" if page.source == "pdf-render" else ""),
        text="\n".join(r["text"] for r in rows),
        rows=rows,
        width=image.width,
        height=image.height,
        mean_score=round(sum(scores) / len(scores), 4) if scores else None,
        steps=steps,
        image=image,
        ms=round((time.perf_counter() - started) * 1000),
    )


def native_page(page: PageInput) -> PageResult:
    lines = [ln.rstrip() for ln in page.text.replace("\r\n", "\n").split("\n")]
    rows = [{"text": ln.strip(), "segments": [], "bbox": None, "score": None} for ln in lines if ln.strip()]
    return PageResult(page.number, page.source, "\n".join(r["text"] for r in rows), rows)
