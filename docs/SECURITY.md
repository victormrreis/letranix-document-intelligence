# Security model

LETRANIX is a single-user local application. Use synthetic or otherwise non-sensitive inputs for evaluation.

## Controls

| Area | Control |
|---|---|
| Network exposure | Binds to `127.0.0.1` only. Requests with another `Host` are refused; browser requests with a foreign `Origin` are refused; no CORS headers. |
| API access | Per-start random session token (obtained only with a custom header, which cross-site pages cannot send without CORS), required on every `/api/*` call except health. |
| Browser hardening | Strict CSP (`script-src 'self'`, `frame-ancestors 'none'`, `object-src 'none'`), `nosniff`, `no-referrer`, `no-store`; originals are served as attachments; extracted text is rendered as text, never HTML. |
| Input handling | Content-based type detection; 50 MiB request cap enforced before multipart parsing (including chunked bodies); configurable per-file and page limits; 40 MP pixel cap; PDFs parsed and images fully decoded at import; damaged/encrypted files rejected with codes. |
| Storage | Originals stored under generated 32-hex identifiers, never the submitted name; names sanitised for display. |
| Database | Parameterised SQL everywhere; dynamic SQL limited to whitelisted fragments (reviewed, annotated); FTS terms quoted as phrases; transactions with version checks prevent lost updates. |
| Export | CSV cells beginning with `= + - @` or control characters are prefixed to prevent formula injection. |
| Integration | Delivery only after explicit authorisation; endpoint restricted to `http://127.0.0.1/localhost`; no redirects followed; proxies ignored; payload contract validated on both sides; idempotency keys. |
| Backup restore | Archive members validated against a strict pattern (no traversal or unexpected files), size-capped, SQLite `integrity_check` before applying, safety backup first. |
| Settings | Every key typed and bounded; unknown keys rejected; inbox must be an existing absolute local folder (no UNC shares); inbox import never moves or deletes files. |
| Logging | Audit details hold identifiers, counts and codes — no document text, field values or credentials (asserted by a test). Errors shown to users never include stack traces or paths. |
| Desktop | Tauri webview has no capabilities (no IPC, filesystem or shell). The shell only starts the local service from the project's virtual environment. |
| Offline | Processing performs no network calls; OCR and workflow tests run with outbound connections denied. |

## Known limits (threat model)

- Any process running as the same OS user can read the workspace and could obtain a session token from the local service. Storage is not encrypted; the audit trail is not tamper-evident.
- Reviewer identity is a self-declared label.
- Parsers (pypdf, pdfium, Pillow) and OCR run in the service process without a sandbox or hard CPU/memory deadline. Do not process hostile files.
- User-defined regex patterns (≤ 200 characters) run without a timeout; templates are a local, trusted configuration.
- One service process per workspace.

## Publication checks (performed for this branch)

Gitleaks over full history and candidate files; `scripts/release_audit.py` with a private denylist kept outside the repository (checks binary types, image EXIF, PDF attachments, fixture hashes, absolute user paths, token/key patterns, remote URL); denylist search over the full Git history; pip-audit; npm audit; manual review of every screenshot (synthetic content only); staged-file review. Automated scans are not proof of absence of all sensitive data and do not establish ownership.

## Desktop dependency advisory

`block-buffer 0.10.4` ([GHSA-qwgh-2vcv-g2f7](https://github.com/advisories/GHSA-qwgh-2vcv-g2f7)) is still reached via `digest → sha2 → tauri-codegen → tauri-macros`, a compile-time proc-macro chain (re-verified with `cargo tree -i` on 2026-10-29). The fix is in 0.12, outside the constraint used upstream. No unreviewed patch is applied; desktop binary distribution remains blocked until upstream remediation or a reviewed mitigation. `glib` and `proc-macro-error` advisories apply only to non-Windows targets.
