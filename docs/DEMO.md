# Three-minute demonstration

Use a fresh local workspace and generated files only. Generate with `python -m letranix demo --data .runtime/presentation`, start the service with that data path, and open the UI.

| Time | Real action |
|---|---|
| 0:00–0:25 | Show the local library and explain that examples are invented and processing stays on this computer. |
| 0:25–1:00 | Select `operational-report.png`, click Process document and wait for actual local OCR. Show the source and extracted text/fields. OCR must be installed; do not simulate success if it is missing. |
| 1:00–1:40 | Compare all fields, correct any OCR errors, identify the reviewer and enter a reason. Approve the review. Point out that approval did not execute integration. |
| 1:40–2:10 | Open the local integration preview, inspect every field, explicitly authorize and show the saved local record. |
| 2:10–2:40 | Open Audit trail and inspect processing, human decision and integration. Search the library by reference or extracted text. |
| 2:40–3:00 | Reload and reopen the document to demonstrate persistence. State that handwriting is experimental and no model training is implemented. |

To demonstrate import separately, use Import documents with one of the generated files. Importing identical bytes returns the existing document. To show a second processing version choose Reprocess; it invalidates the current approval for future integration and requires new review. Do not approve deliberately incorrect OCR values just to finish the presentation.
