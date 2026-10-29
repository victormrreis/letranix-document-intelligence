"""OCR preprocessing benchmark on generated, degraded synthetic pages.

Character error rate (CER) is the Levenshtein distance between recognised and
true text divided by the true length, after collapsing whitespace. Each
preprocessing configuration runs on the same images, so differences come from
preprocessing alone. Results decide the default settings; they are not a
general OCR accuracy claim.
"""

import json
import random
import time
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

from . import ocr
from .demo import render

TEXTS = [
    ["Order No.: SO-48213", "Requested by: Ana Exemplo", "Location: North Annex 3",
     "Date: 2026-07-14", "Description: Calibrate the sample scale."],
    ["Report ID: IR-90517", "Site: Demo Plant South", "Inspector: Bruno Ficticio",
     "Result: Conditional", "Notes: Valve 12 requires follow-up."],
]


def degrade(image: Image.Image, kind: str, rng: random.Random) -> Image.Image:
    if kind == "skew":
        return image.rotate(3.5, resample=Image.BICUBIC, expand=True, fillcolor="#fbfaf6")
    if kind == "low-contrast":
        return ImageEnhance.Contrast(image).enhance(0.25)
    if kind == "noise":
        import numpy as np

        arr = np.asarray(image).astype(np.int16)
        noise = np.random.default_rng(rng.randint(0, 10**6)).normal(0, 38, arr.shape)
        return Image.fromarray(np.clip(arr + noise, 0, 255).astype("uint8"))
    if kind == "small-blur":
        small = image.resize((image.width * 2 // 5, image.height * 2 // 5))
        return small.filter(ImageFilter.GaussianBlur(0.7))
    return image


CONFIGS = {
    "none": {},
    "gray+contrast": {"grayscale": True, "autocontrast": True},
    "gray+contrast+deskew": {"grayscale": True, "autocontrast": True, "deskew": True},
    "gray+contrast+deskew+upscale": {"grayscale": True, "autocontrast": True, "deskew": True, "upscale": True},
    "all+denoise": {"grayscale": True, "autocontrast": True, "deskew": True, "upscale": True, "denoise": True},
}
KINDS = ["clean", "skew", "low-contrast", "noise", "small-blur"]


def levenshtein(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def cer(got: str, truth: str) -> float:
    g, t = " ".join(got.split()), " ".join(truth.split())
    return levenshtein(g, t) / max(1, len(t))


def run(output: Path | None = None) -> dict:
    rng = random.Random(7)  # nosec B311 - reproducible synthetic data, not security
    cases = [(kind, i, degrade(render(lines, size=(1500, 700)), kind, rng))
             for kind in KINDS for i, lines in enumerate(TEXTS)]
    results: dict = {name: {} for name in CONFIGS}
    for name, options in CONFIGS.items():
        for kind, i, image in cases:
            started = time.perf_counter()
            page = ocr.ocr_page(ocr.PageInput(1, image=image, source="image"), options)
            elapsed = time.perf_counter() - started
            truth = "\n".join(TEXTS[i])
            results[name].setdefault(kind, []).append((cer(page.text, truth), elapsed))
    summary = {}
    for name, by_kind in results.items():
        all_cer = [c for runs in by_kind.values() for c, _ in runs]
        all_t = [t for runs in by_kind.values() for _, t in runs]
        summary[name] = {
            "mean_cer": round(sum(all_cer) / len(all_cer), 4),
            "mean_seconds": round(sum(all_t) / len(all_t), 2),
            "cer_by_degradation": {k: round(sum(c for c, _ in v) / len(v), 4) for k, v in by_kind.items()},
        }
    report = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "engine": "rapidocr-onnxruntime 1.4.4 (CPU)",
              "images": len(cases), "degradations": KINDS, "configs": CONFIGS, "results": summary}
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
