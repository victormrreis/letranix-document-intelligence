# Capability matrix

Status legend: **Validated** — implemented and covered by executed tests · **Limited** — real, with documented limits · **Partial** — not the full flow · **Absent** · **Blocked** — a technical, legal or operational dependency prevents it.

"v0.1" is the state found before this work; tests named are in `tests/` (pytest) or `tests/browser/` (Playwright, *E2E*).

## 1 · Document hub

| ID | Capability | v0.1 | Now | Evidence |
|---|---|---|---|---|
| H1 | Import (upload, drag-and-drop, multi-file) | upload only | Validated | E2E import of 4 files; `test_path_safe_names_and_deduplication` |
| H2 | Import from a configured inbox folder | Absent | Validated | `test_settings_are_validated_and_take_effect` |
| H3 | Organise by document type | 4 hard-coded categories | Validated | classifier + "Change type"; `test_change_type_reextracts_without_ocr` |
| H4 | Persist documents and metadata | Validated | Validated | restart tests |
| H5 | Search names, OCR text and field values | `LIKE` on name/text | Validated (FTS5) | `test_search_filters_pagination_and_injection`, E2E search |
| H6 | Filter by type, status, date, issues; sort; paginate | status/category | Validated | same |
| H7 | View original (images, PDF pages, text) | iframe/img | Validated | `test_skewed_image_ocr…` page image endpoint, E2E viewer |
| H8 | View OCR result with boxes and scores | Absent | Validated | E2E "Recognised text" tab; page `rows` in API |
| H9 | Processing history (jobs, timings, errors) | job states | Validated | History tab; `processing.completed` audit details |
| H10 | Identify failed documents and retry | Partial | Validated | `test_empty_ocr_result_and_disabled_engine_fail_cleanly`, *Retry* button |
| H11 | Reprocess | Validated | Validated | `test_reprocessing_invalidates_previous_approval` |
| H12 | Export (CSV/JSON of approved records, per-document JSON) | Absent | Validated | `test_exports_csv_safe_and_json`, E2E CSV download |
| H13 | Archive, unarchive, confirmed permanent delete | Absent | Validated | `test_archive_and_delete_keep_audit` |
| H14 | State recovered after restart | Validated | Validated | `test_full_review_flow…restart`, `test_interrupted_job_is_requeued_then_failed` |

## 2 · OCR pipeline

| ID | Capability | v0.1 | Now | Evidence |
|---|---|---|---|---|
| O1 | PDF and image intake with content-based type check | PDF/PNG/JPEG | Validated (+TIFF, WebP) | `test_invalid_documents_rejected_at_import` |
| O2 | Corrupted, encrypted, empty, oversized, too many pages | Partial (at processing) | Validated (at import) | same + `test_encrypted_and_oversized_and_page_limits` |
| O3 | Multi-page documents | native PDF only | Validated | `test_scanned_multipage_pdf_is_rendered_and_ocred` |
| O4 | Embedded PDF text when present | Validated | Validated | `test_native_pdf_table` |
| O5 | Scanned PDF OCR | Absent ("export to PNG") | Validated | same as O3 |
| O6 | Preprocessing (grayscale, contrast, denoise, deskew, upscale) | Absent | Validated, measured | [benchmark](evaluation/ocr-preprocessing.json); deskew asserted |
| O7 | Orientation correction | Absent | Validated | `test_rotated_form_orientation_and_layout` |
| O8 | Region/layout use (rows, cells, label-below) | Absent | Limited | layout rules; no general region segmentation |
| O9 | Background processing, progress, cancellation, crash recovery | synchronous | Validated | `test_cancel_queued_and_running_jobs`, `test_background_worker…`, recovery test |
| O10 | Errors and timings recorded | Partial | Validated | job `timings`, audit codes |
| O11 | Field-level traceability (page, row, box, score) | evidence text | Validated | `test_layout_label_below_and_low_score` |
| O12 | Alternative engines (Tesseract, EasyOCR, PaddleOCR) | — | Absent | evaluated, not integrated — see OCR_PIPELINE.md |
| O13 | Works on unseen documents | — | Validated | all tests generate documents at run time |

## 3 · Structured extraction

| ID | Capability | v0.1 | Now | Evidence |
|---|---|---|---|---|
| X1 | Dates, identifiers, numbers, amounts, enums | 5 text fields | Validated | `test_dates`, `test_money`, `test_enum_and_identifier_normalisation` |
| X2 | Configurable document types and fields | Absent | Validated | `test_templates_crud_rules`, Document types page |
| X3 | Validation rules (required, regex, options, calendar) | date/category only | Validated | `test_review_validation` |
| X4 | Tables (line items) | Absent | Limited | `test_table_extraction_native_text`; simple column layouts only |
| X5 | Positioned form fields | Absent | Validated | `test_layout_label_below_and_low_score`, rotated form |
| X6 | No invented values; ambiguity surfaced | Partial | Validated | `test_missing_optional_fields_are_never_invented`, `test_ambiguity_lists_candidates`, evaluation `invented_values = 0` |
| X7 | Recognised vs inferred vs confirmed distinguished | Absent | Validated | field `source`/`rule`, review `provenance` |
| X8 | Confidence methodology documented | "none invented" | Validated | REVIEW_WORKFLOW.md § Confidence |

## 4 · Assisted review

| ID | Capability | v0.1 | Now | Evidence |
|---|---|---|---|---|
| R1–R4 | Open, side-by-side page and fields, edit, validate | Validated (basic) | Validated | E2E review |
| R5 | Mark inconsistencies | Absent | Validated | E2E flag blocks approval; `test_reject_with_flag_then_reopen_and_approve` |
| R6 | Record changes (provenance, corrections) | Partial | Validated | `test_full_review_flow…` |
| R7–R8 | Approve / reject and persist | Validated | Validated | same |
| R9 | History | Validated | Validated | E2E History tab |
| R10 | Reopen | Absent | Validated | `test_reject_with_flag_then_reopen_and_approve` |
| R11 | Forward approved records | Validated (local) | Validated | see I-rows |
| R12 | No silent loss of edits | Absent | Validated | E2E draft restored after reload; leave-page confirmation |
| R13 | Scrollable modals, responsive at 390–1920 px | Partial | Validated | E2E overflow assertions at 1920/1366/390 |

## 5 · Feedback and learning

| ID | Capability | v0.1 | Now | Evidence |
|---|---|---|---|---|
| L1 | Structured correction storage | Absent | Validated | `corrections` table |
| L2 | Rules learned from validations (alias, value-map, char-map) | Absent | Validated | `test_learning_alias_activates…`, `test_learned_rules_are_applied…` |
| L3 | Rule lifecycle (support threshold, contradiction auto-disable, manual toggle) | Absent | Validated | same |
| L4 | Document-type learning | Absent | Validated | `test_classifier_learns_custom_type_from_approvals` |
| L5 | Measured before/after with train/validation/test separation | Absent | Validated | `test_evaluation_shows_measured_gain…`, [learning.json](evaluation/learning.json) |
| L6 | Model training (neural) | — | Absent | intentionally not claimed |

## 6 · Integrations

| ID | Capability | v0.1 | Now | Evidence |
|---|---|---|---|---|
| I1 | Adapter interface and contract | Protocol stub | Validated | `Adapter`, `letranix.record/v1`, `validate_payload` |
| I2 | Queue (outbox), retries, backoff, permanent/transient | Absent | Validated | `test_retry_after_outage…`, `test_permanent_rejection…`, `test_unavailable_destination…` |
| I3 | Idempotency / duplicate prevention | Validated (local) | Validated (HTTP) | redelivery returns `duplicate: true` |
| I4 | Real demo integration against a fictitious API | Absent | Validated | `test_delivery_reaches_destination_with_contract`, E2E verifies at destination |
| I5 | Connection to private enterprise systems | — | Blocked | not authorised; out of scope by design |

## 7 · Audit

| ID | Capability | v0.1 | Now | Evidence |
|---|---|---|---|---|
| A1 | Import, processing, reprocessing, extraction, change, approval, rejection, export, integration, error, settings, backup | Partial | Validated | event list in Audit page |
| A2 | Consultable in the UI with filters | per document | Validated | Audit trail page; E2E |
| A3 | No document text or credentials in logs | Validated | Validated | `test_audit_does_not_contain_document_content` |
| A4 | Tamper-evidence | — | Absent | documented limitation |

## 8 · Settings and persistence

| ID | Capability | v0.1 | Now | Evidence |
|---|---|---|---|---|
| S1 | Persisted, validated settings that change behaviour | Absent | Validated | `test_settings_are_validated_and_take_effect`, OCR-off test, limits test, E2E adapter switch |
| S2 | Document directory (inbox), processing limits, OCR engine and preprocessing, review and learning parameters, integration, theme/density | Absent | Validated | Settings page |
| S3 | OCR language selection | — | Blocked | the installed PP-OCR model is multilingual (Chinese/Latin); no language packs to choose between |
| S4 | Backup and restore | Absent | Validated | `test_backup_restore_and_traversal_rejection` |
| S5 | Versioned schema migrations | Absent | Validated | `test_migration_from_v01_workspace`; live v0.1 workspace upgraded |

## 9 · Platform

| ID | Capability | Now | Evidence |
|---|---|---|---|
| P1 | Desktop app opens and manages its service | Validated | Manual run: service started in 4.5 s, window opened, service stopped on close |
| P2 | Signed installer / bundled Python | Blocked | Rust advisory in build chain + rights review; see SECURITY.md |
| P3 | CI | Limited | workflow updated; remote results only after the push runs |
