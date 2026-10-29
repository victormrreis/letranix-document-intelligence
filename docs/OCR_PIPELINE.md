# OCR pipeline

## Inputs

Format is identified from content, never the file name: `%PDF-`, PNG, JPEG, TIFF (`II*`/`MM*`), WebP (`RIFF…WEBP`) and UTF-8 text without control characters. At import LETRANIX also opens the file: PDFs are parsed (encrypted and damaged files are rejected), images are fully decoded (truncated files are rejected), and page/frame counts are checked against the configured limit. Limits: configurable file size (1–50 MiB, default 10), pages (1–200, default 30), 40 megapixels per page, and a 50 MiB hard request cap applied before multipart parsing.

## Per-page strategy

| Page | Method | Recorded as |
|---|---|---|
| Text file | Read directly | `native-text` |
| PDF page with ≥ 20 embedded characters (setting on) | `pypdf` text extraction | `pdf-native` |
| PDF page without text (scanned) | Rendered with pdfium at the configured DPI (default 200), then OCR | `ocr-rapidocr-pdf` |
| PNG/JPEG/WebP, each TIFF frame | EXIF orientation applied, then OCR | `ocr-rapidocr` |

The engine is [RapidOCR](https://github.com/RapidAI/RapidOCR) 1.4.4 (PP-OCR detection, direction classification and recognition models on ONNX Runtime, CPU). It runs offline; tests deny network access while it runs. Setting `ocr.engine = none` disables image OCR without affecting native text.

## Preprocessing — measured

Steps are individual settings so their effect can be verified. `python -m letranix benchmark` renders synthetic pages, degrades them (3.5° skew, low contrast, Gaussian noise, 40% downscale + blur), runs real OCR per configuration and computes the character error rate (Levenshtein distance / reference length).

| Configuration | Mean CER | Small + blurred | Noise | Mean time / page |
|---|---|---|---|---|
| none | 1.83% | 6.76% | 1.19% | 2.74 s |
| grayscale + autocontrast | 1.75% | 7.16% | 0.79% | 2.34 s |
| + deskew | 1.75% | 7.16% | 0.79% | 1.92 s |
| + upscale | 1.19% | 4.38% | 0.79% | 2.11 s |
| **+ median denoise (default)** | **0.87%** | **3.57%** | 0.79% | 1.98 s |

10 images × 5 configurations, Windows 11, 8 logical CPUs ([raw results](evaluation/ocr-preprocessing.json)). The sample is small: it justifies the defaults, not a general accuracy claim. Deskew did not change CER — PP-OCR tolerates small angles — but it keeps rows horizontal, which the row grouping and layout rules depend on, so it stays on.

## Orientation

If more than half of the multi-character boxes are much taller than wide, the page is turned 90°: the recogniser can still read the crops, but reading order and layout are lost. The page is re-run at 90° and 270° and the result with the best score-weighted character count wins. Weak results (fewer than 15 characters or mean score < 0.6) also try 180°. The applied rotation is listed in the page's processing steps.

## From boxes to rows

Segments are grouped into rows by vertical overlap (> 50% of the smaller height) and sorted left to right. Rows keep their segments, so extraction can split a row into cells at large horizontal gaps (column layouts) and find the cell *below* a label (forms). Each segment keeps the engine's recognition score; rows below `ocr.min_line_score` (default 0.6) are highlighted in the viewer and flagged on any field whose evidence they hold.

## Known OCR behaviours

- PP-OCR sometimes drops spaces on large text. `respace()` inserts a space at lowercase→Capitalised boundaries ("CarlaModelo" → "Carla Modelo"). Per-character box gaps were tried and rejected: measured intra-word gaps were as wide as real word gaps. Lowercase run-ons ("sampleforms") remain for the reviewer, and label matching tolerates missing spaces ("Ordernumber").
- Handwriting-style fonts are recognised on the generated fixture; real handwriting is not evaluated.
- Engines evaluated but not integrated: Tesseract (not installed in the validation environment; would require a system install) and EasyOCR (requires PyTorch, several hundred MB — not justified for CPU-only local use). The engine setting is the extension point.
