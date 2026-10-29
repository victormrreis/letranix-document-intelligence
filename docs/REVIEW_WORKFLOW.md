# Extraction, review and learning

## Document types

A document type (template) lists fields with a key, label, type, the labels that introduce them in documents, whether they are required, and optionally a regex format or the allowed options. A type may also declare a line-item table. Five built-in, generic types ship read-only (Generic record — compatible with v0.1 data — Service order, Invoice, Inspection report, Administrative request). Custom types are created or copied from the UI (*Document types*) or `POST /api/templates`, and are validated (unique keys, compilable patterns ≤ 200 characters, 1–30 fields).

## How a field is found

Rules are tried in order and the rule used is stored with the value.

| Rule | Example | Source |
|---|---|---|
| `label` | `Order No.: SO-10423`, `Data - 15/03/2026` | recognized |
| `label-cell` | OCR cells `Requester` · `Ana` on one row | recognized |
| `label-below` | `Order number` with `SO-20981` underneath (forms) | recognized |
| `learned-alias` | `Raised by: Caio` after reviewers taught that label | recognized (learned) |
| `unique-pattern` | the only date / only pattern match in a document whose label is unknown — **required fields only** | inferred |
| `learned-value-map`, `learned-char-map` | `Alta` → `high`, `SO-1O23` → `SO-1023` | inferred |

Label matching ignores case, accents and missing spaces, accepts `:`, `-`, `=`, `#`, "No."/"nº" suffixes, and requires a separator unless the value parses as the field's type (so prose such as "Description of the work…" is not mistaken for a field). A cell that is itself another field's label is never used as a value (column headers).

Values are normalised by type: ISO dates from `2026-03-15`, `15/03/2026`, `2 Apr 2026`, `15 de março de 2026` (ambiguous day/month is flagged); amounts from `R$ 1.234,56`, `$1,234.56`; identifiers upper-cased; enums matched to the allowed options. If several different valid values exist the field is marked ambiguous and the candidates are offered. **Missing optional fields are never filled**; missing required fields are only inferred from a unique typed match and labelled as such.

## Confidence

LETRANIX does not compute an accuracy percentage per field. It shows the facts it has: the rule used, the evidence text and position, and the OCR engine's recognition score for that line (0–1, reported by PP-OCR). The document-type percentage is a relative likelihood among types, not a probability of correctness.

## Review

- The viewer shows the processed page with every OCR box; focusing a field highlights its evidence box and jumps to its page.
- Each field shows "Read from label", "Inferred", "Not found", or "Edited"; issues are listed under the input.
- *Flag inconsistency* records a note; flagged fields block approval and are stored with a rejection.
- Edits are stored as a draft in the browser (per document version) and restored after reload; leaving the page with unsaved edits asks for confirmation.
- **Approve** validates all fields server-side (`422` with per-field messages). **Reject** requires a reason. Decisions carry the version; a stale decision returns `409`.
- **Reopen** (approved or rejected) requires a reason and returns the document to review; prior decisions remain in history.
- **Change type** re-extracts the stored OCR rows with another template without re-running OCR, creating a new version.
- Each decision stores per-field provenance: `confirmed`, `corrected`, `entered`, or `empty`.

## Learning from approvals

On approval, every field whose confirmed value differs from the extraction is recorded in `corrections`, and rule evidence is derived:

- **alias**: the field was not found, and the confirmed value appears next to an unknown label in this document → that label;
- **value-map**: a text/enum value was corrected to a similar value (≥ 0.6 similarity, or any enum fix);
- **char-map**: a typed value differed by at most three short substitutions (e.g. `O`→`0`).

A rule counts *documents*, not reviews. It becomes active once supported by `learning.min_support` documents (default 2). Confirming a value produced by a rule adds support; correcting it adds a contradiction, and a rule is disabled automatically when contradictions exceed support. Rules can be toggled or deleted on the *Learning* page and record how often they were applied. Character maps are applied only when they turn an invalid value into a valid one.

The document-type classifier (multinomial Naive Bayes over word tokens, Laplace smoothing) is fitted from the latest approved review per document plus each template's keywords and labels as a prior, and is refitted whenever approvals change. Multi-word keywords are also matched on space-stripped text so run-on OCR headings ("SERVICEORDER") still count.

### Measured effect

`python -m letranix evaluate` (also *Learning → Run evaluation*) generates synthetic documents with three independent seeds. **Train** (60) goes through the real import → process → correct → approve path; **validation** (30) chooses the activation threshold; **test** (60) is scored once with template knowledge only and once with what was learned. Documents mix known labels with recurring unknown ones, OCR-style `0/O` and `1/I` confusions, Portuguese option synonyms and absent optional fields; field values are drawn independently per split.

| Test split (60 documents, 338 field values) | Before learning | After learning |
|---|---|---|
| Field exact-match accuracy | 54.4% | **95.3%** |
| Document-type accuracy | 85.0% | **100%** |
| Values produced where truth is empty | 0 | **0** |

Validation chose `min_support = 1` (validation accuracy 97.0% at 1, 95.9% at 2, 89.4% at 3); 29 alias, 6 char-map and 4 value-map rules were active. Remaining errors are mostly enum synonyms that only ever appeared under an unknown label (inspection `result`: 53%) and identifiers with confusions in positions the learned maps did not cover. [Raw report](evaluation/learning.json). These figures describe synthetic data only.
