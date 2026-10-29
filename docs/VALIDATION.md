# Executed validation — 2026-10-29

Local run on Windows 11, Python 3.12.10, Node 24.21.0, Rust 1.98.1 (8 logical CPUs). These are executed results; GitHub Actions results are separate and appear on the pull request.

| Check | Command | Result |
|---|---|---|
| Backend suite | `python -m pytest -q` | **75 passed** (≈ 90 s), 0 skipped |
| Browser E2E | `npm run test:e2e` | **3 passed** (≈ 75 s) |
| TypeScript | `npm run typecheck` | clean |
| ESLint (incl. react-hooks rules) | `npm run lint` | clean |
| Prettier | `npm run format:check` | clean |
| Ruff | `python -m ruff check letranix tests scripts` | clean |
| Bandit | `python -m bandit -r letranix` | no issues (4 SQL builders annotated after review: only whitelisted fragments are interpolated) |
| pip-audit | `python -m pip_audit` | no known vulnerabilities |
| npm audit | `npm audit` | 0 vulnerabilities |
| Gitleaks 8.30.1 | history + candidate files | no leaks |
| Release audit + private denylist | `scripts/release_audit.py --terms-file <private>` | no findings after staging; denylist: 0 matches in files and full history |
| Tauri | `cargo build` | builds; desktop run verified manually (below) |

## What the suites cover

**pytest** (`tests/`): extraction units (dates, amounts, enums, labels, prose rejection, optional-field non-invention, ambiguity, layout label-below with OCR boxes, low-score flag, tables, learned rules, template validation); full flow with correction → provenance → corrections → restart persistence; invalid inputs (empty, unsupported, control characters, corrupt PDF, truncated PNG, encrypted PDF, size and page limits); OCR disabled and empty images; review validation (stale version, bad date/enum, missing required, missing reason, extra field, flagged field); reject → reopen → approve; reprocessing invalidating approval; type change without OCR; local ledger idempotency; rejected reviews cannot integrate; cancellation of queued and running jobs; crash recovery (requeue, then fail); background worker; alias learning with support threshold, confirmation and contradiction auto-disable; classifier learning a custom type; template rules; settings validation and effect (limits, endpoint loopback-only, inbox); FTS search, filters, pagination and FTS/SQL syntax as data; archive/delete with retained audit; CSV formula-injection neutralisation; audit free of document content; backup → delete → restore and zip traversal rejection; API boundaries (token, Host, Origin, body cap); migration of a genuine v0.1 database; offline operation; learning evaluation gain.
**Real OCR** (`test_ocr.py`): skewed image (deskew recorded, boxes, scores), two-page scanned PDF rendered and OCRed, rotated low-quality form (orientation recovered, label-below fields), native PDF table — all with network access denied.
**Real HTTP** (`test_integration_http.py`): the fictitious API runs on a real port; delivery and contract, injected 503 then retry, re-delivery after a simulated crash returns `duplicate`, injected 422 → failed → manual retry, unreachable destination exhausting attempts.
**E2E** (`tests/browser`): settings change, multi-file import, background OCR, field values, draft restored after reload, approval, history provenance, explicit send, delivery confirmed in the UI *and* directly at the destination, CSV download content, reload persistence; multi-page viewer, table values, flag blocking approval, search, audit, learning evaluation from the UI, no horizontal overflow at 1920×1080, 1366×768 and 390×844; damaged-file error message.

## Desktop run (manual, recorded)

With nothing on port 8795, `letranix-desktop.exe` started the service hidden; `/api/health` answered after 4.5 s; the window titled "LETRANIX - Document Intelligence Platform" displayed the workspace; closing the window stopped the child service (port closed). That workspace was a v0.1 workspace and was migrated to schema 2 on open. Full mouse/keyboard automation of WebView2 was not performed; UI flows are validated in Chromium against the same frontend and service.

## Measurements

| Measure | Value | Source |
|---|---|---|
| OCR per image page (1500×700, default preprocessing) | ≈ 2.0 s | [ocr-preprocessing.json](evaluation/ocr-preprocessing.json) |
| OCR per scanned A4 page at 200 DPI | ≈ 6 s | job timings of `scanned-request.pdf` |
| Text document through the full pipeline | 12.7 documents/s | [performance.json](evaluation/performance.json) |
| Import (hash, validate, store, index) | 15 ms / document | same |
| Search, 300 documents (median / p95) | 5.2 ms / 13 ms | same |
| Workspace open | 23–40 ms | same |
| Peak memory, 300 text documents (no OCR model) | 44 MB | same |
| Desktop: service ready after launch | 4.5 s | manual run |
| Learning: test field accuracy before → after | 54.4% → 95.3% | [learning.json](evaluation/learning.json) |

## Not covered

- Real handwriting; non-Latin scripts; very large (> 30 page) scanned documents beyond the configured limit.
- Native WebView2 interaction automation; installer packaging.
- Hostile-input fuzzing and parser sandboxing.
- Remote CI on this branch until it runs on GitHub.
