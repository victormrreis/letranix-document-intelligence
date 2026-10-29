# Five-minute demonstration

Use a fresh workspace and generated files only: `python -m letranix demo --data .runtime/presentation`, then `python -m letranix serve --data .runtime/presentation --with-destination`.

| Time | Action (all real) |
|---|---|
| 0:00 | **Overview** — live counts from the database; six synthetic documents already processed in the background. |
| 0:30 | **Documents** — search "Records Office" (matches OCR text of a scanned PDF); filter by type; show the issue counts. |
| 1:00 | Open `inspection-report.png` — page deskewed by −2°, OCR boxes with scores; click a field's evidence to highlight it on the page. |
| 1:40 | Correct *Notes*, reload the page to show the restored draft, write a note and **Approve**. History shows per-field provenance. |
| 2:20 | Open `rotated-field-form.jpg` — orientation recovered; fields read *below* their labels. Flag an inconsistency and show that approval is blocked. |
| 3:00 | Settings → Destination `http-demo`. Back on the approved document: **Send to destination**, preview, authorise. Integrations shows *delivered* and the record read back from the fictitious API. |
| 3:40 | Inject `POST :8797/admin/faults?count=1&status=503`, send another approved document: the outbox schedules a retry and then delivers. |
| 4:20 | **Learning → Run evaluation** — before/after accuracy on a held-out synthetic test split. |
| 4:50 | **Audit trail** — every step, without document content. |

Do not approve wrong values to finish faster; the point is that the reviewer decides.
