# Getting started

Use Windows with Python 3.12, Node 24 and npm. The tested environment is recorded in VALIDATION.md. Create a new virtual environment; do not reuse operational environments or import existing databases. `requirements-lock.txt` captures the validated Python dependency set including the optional OCR engine and development tools. `requirements.txt` is the smaller runtime set; `requirements-ocr.txt` adds OCR. Keep the lockfile for reproduction.

Run the commands in the README from the repository root. The app binds only to `127.0.0.1`. The frontend build and API share the same origin; no cross-origin development proxy is configured. For frontend development run `npm run build` after edits and use the local service, or use Vite for visual development without API connectivity.

Data defaults to `.runtime/workspace` and never belongs in Git. Override with `--data <new-evaluation-directory>` or `LETRANIX_DATA`. `--port` overrides `LETRANIX_PORT`. The `.env.example` documents names; dotenv files are not automatically loaded. Demo generation is explicit:

```powershell
.\.venv\Scripts\python.exe -m letranix fixtures
.\.venv\Scripts\python.exe -m letranix demo --data .runtime/demo
.\.venv\Scripts\python.exe -m letranix serve --data .runtime/demo --port 8795
```

The seed command adds only missing content hashes; it does not reset or delete data. Changing fixture fonts between hosts can change image hashes. Never point it at a pre-existing operational folder. Back up an evaluation workspace only while the service is stopped, copying both database and document files together.

For the optional desktop shell install Rust/MSVC C++ build tools and WebView2, start the service on port 8795, then run `npm run tauri -- dev`. The shell does not start or package Python. `cargo check --manifest-path src-tauri/Cargo.toml` checks Rust compilation. Installer creation and signing are intentionally pending.

Stop the local service with Ctrl+C. Restart with the same `--data` path to retain documents and decisions; the browser session token changes at each service start. Reload the browser to establish a new local session.
