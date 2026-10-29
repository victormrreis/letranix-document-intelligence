# Executed validation — 2026-10-29

Local Windows evaluation, Python 3.12, Node 24.21.0. These are executed results, not a remote CI claim.

| Check | Result |
|---|---|
| Backend functional/regression suite | 27 passed; real local image OCR included; no skipped tests in this environment |
| Browser workflows | 2 passed, including import, OCR, correction, approval, explicit integration, reload, search, reprocessing and integration of a new reviewed version |
| Layout | 1920×1080, 1366×768, 911×512 (equivalent CSS viewport for 150% at laptop resolution), 390×844; no horizontal overflow asserted |
| Frontend | TypeScript check, production Vite build, ESLint and Prettier check passed |
| Python | Ruff lint/format and Bandit passed |
| SQLite | Integrity and foreign-key consistency checked in demo tests; restart persistence and interrupted-job recovery passed |
| Strict isolation | Independent source copy run in Python isolated mode; original-path reads and external connections denied by an audit hook. Image import, real offline OCR, review, explicit integration and restart passed; zero original access attempts |
| Native desktop | Cargo check and debug build passed; independently built Tauri window opened and displayed five synthetic documents |
| Python advisories | pip-audit reported no known vulnerabilities after upgrading the virtual environment's pip to 26.2.2 |
| npm advisories | npm audit reported no known vulnerabilities |
| Rust advisories | 405 registry packages queried through OSV; 3 affected package names; see SECURITY.md. Desktop distribution blocked |
| Secrets | Gitleaks 8.30.1 found no leaks in the inspected candidate snapshot; final staged audit recorded privately |
| Sensitive-reference audit | Local scan with external private terms, credential/identifier heuristics, candidate filenames, binary metadata and fixture hashes; no findings after repairs |

The Python suite emits one upstream Starlette deprecation warning about the test client's `httpx` integration. It did not prevent the tests from passing. Native desktop testing established opening/rendering; complete mouse/keyboard workflow automation was validated in Chromium rather than claimed for WebView2. No standalone signed installer was built.

An early OCR fixture using a small fallback font produced letter/digit confusion in its reference. The printed fixture was regenerated with clearer typography; the final real OCR test passed. This is fixture-specific validation, not an OCR quality benchmark. The handwritten-style and degraded examples are available for exploration but no accuracy claim is made for them.

Screenshots under `screenshots/` come from automated browser interaction using only generated examples. Python tests use temporary evaluation workspaces; browser tests start their own fresh local service and workspace automatically:

```powershell
.\.venv\Scripts\python.exe -m letranix fixtures
npx playwright install chromium
npm run test:e2e
```

The browser suite creates ignored `.runtime/browser-*` workspaces, preserving them for inspection; it does not delete existing data. Do not run another service on port 8796 during that suite.

## Publication state

**SOURCE-ONLY PORTFOLIO PREVIEW, authorized on 2026-10-29.** No open-source license is granted and publication is not a legal clearance statement. Application licensing and any broader distribution rights remain under review. The Tauri build dependency advisory still blocks desktop binary distribution pending compatible upstream remediation or a reviewed mitigation. Dependency and secret scanners are not proof of complete safety. Git was initialized independently, without inherited history; the public source contains only the reviewed application, synthetic examples and documentation. Local results above are distinct from GitHub Actions results.
