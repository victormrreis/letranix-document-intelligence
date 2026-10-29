# Human review

The document workspace shows the source, processing method and extracted fields. Images and PDFs are previewed; text extraction is shown verbatim. Download returns the original bytes with an attachment disposition.

Every corrected field remains distinguishable from the stored automatic value. Missing fields must be supplied before approval. Date must be valid ISO `YYYY-MM-DD`; category must be one of the four demo categories. Repeated labels show a visible ambiguity warning; the reviewer must determine the correct value from source evidence.

Approval requires all five fields, reviewer label and a meaningful reason. Rejection also requires a reason and preserves its snapshot. Saving either decision never integrates. An approved document offers a separate preview of the exact reviewed values, followed by an explicit authorization button. Only that action writes a local demonstration ledger record; there is no external adapter connection.

Reprocessing preserves old jobs and reviews but requires a new review. A stale version or repeated decision is rejected; repeated integration of the same review returns the existing result. The audit tab shows import, processing, decisions and local integration.

Unsaved edits exist only in browser memory and are lost on reload. The app does not silently persist drafts to localStorage. Actor labels are self-declared in this single-user demonstration; they are not proof of identity. Record corrections responsibly and do not use the application as a production compliance system.
