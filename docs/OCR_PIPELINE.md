# OCR and extraction

1. Inspect actual bytes, not the supplied filename extension. Accept UTF-8 text, PDF signatures, PNG and JPEG signatures; bound file content to 10 MiB.
2. Native text passes through UTF-8 decoding. pypdf extracts native PDF text (unencrypted, at most 30 pages). Scanned PDFs without native text produce a visible failed processing job.
3. Images are checked with Pillow (12-megapixel limit). Optional `rapidocr-onnxruntime` runs locally, using the pretrained assets installed with that dependency. No operational models, local caches or fine-tuned weights are imported. OCR invocation is serialized.
4. Parse labeled lines into reference, organization, category, date and description. Retain the source line as evidence and flag repeated labels. Missing labels remain blank. Extraction text is limited to 200,000 characters.
5. Save a processing version and require human review before approval.

OCR character recognition is fallible, including confusion between letters and digits in references. A successful job is not a correct document. No model confidence is promoted to field-level accuracy; the API returns `null` for field confidence. No accuracy benchmark is claimed from the synthetic demo.

The handwriting-style fixture is rendered from an installed OS font when available, with a printed fallback. It is not a real handwritten document and does not establish handwriting performance. The degraded scan is created from invented text with downsampling, blur and JPEG compression.

Correction history does not change extraction rules, retrieve similar cases, adjust parameters, or fine-tune a model. Future learning capabilities require separate implementation and evaluation.
