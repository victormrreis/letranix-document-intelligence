# Getting started

Requirements: Windows with Python 3.12 and Node 24 (validated). Rust (MSVC toolchain) and WebView2 only for the desktop shell. Linux/macOS should work for the service but are not validated.

## Install

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
npm ci
npm run build
```

`requirements.txt` is the runtime minimum (no OCR); add `requirements-ocr.txt` for image OCR; `requirements-lock.txt` is the exact validated set including test and audit tools.

## Run

```powershell
.\.venv\Scripts\python.exe -m letranix demo                      # synthetic fixtures → demo/synthetic, imported into .runtime/workspace
.\.venv\Scripts\python.exe -m letranix serve --with-destination  # UI + API on http://127.0.0.1:8795, demo records API on :8797
```

| Command | Purpose |
|---|---|
| `serve [--data DIR] [--port N] [--with-destination]` | Start the service (and optionally the fictitious records API on `port + 2`). |
| `demo [--data DIR]` | Generate fixtures and import any not yet present (never deletes). |
| `fixtures` | Only regenerate `demo/synthetic` and its hash manifest. |
| `mock-destination [--port N] [--data DIR]` | Run the fictitious records API alone. |
| `evaluate [--output FILE]` | Learning benchmark (train / validation / test). |
| `benchmark [--output FILE]` | OCR preprocessing benchmark. |

`LETRANIX_DATA` and `LETRANIX_PORT` override the defaults. Data lives in the workspace folder (`letranix.db`, `documents/`, `pages/`, `backups/`) and never belongs in Git.

## Demo integration over HTTP

Start with `--with-destination`, then *Settings → Integration → Destination = http-demo* (endpoint `http://127.0.0.1:8797/records`). Approve a document, choose *Send to destination*, and check *Integrations → Records held by the destination*. Inject failures to see retries: `POST http://127.0.0.1:8797/admin/faults?count=2&status=503`.

## Desktop

```powershell
cargo build --manifest-path src-tauri/Cargo.toml
.\src-tauri\target\debug\letranix-desktop.exe
```

The shell reuses a running service or starts `.venv` Python with `-m letranix serve` from the project root (override with `LETRANIX_HOME` / `LETRANIX_PYTHON`) and stops it when the window closes. `npm run tauri -- dev` also works with a running service.

## Develop

Python lint/format: `ruff check`, `ruff format`. Frontend: `npm run typecheck`, `npm run lint`, `npm run format`. Tests: `python -m pytest -q`, `npm run test:e2e` (starts its own service on port 8805 and destination on 8807 with a fresh workspace under `.runtime/`). Regenerate README screenshots and the GIF: `LETRANIX_SCREENSHOTS=1 LETRANIX_VIDEO=1 npm run test:e2e` then `python scripts/make_demo_gif.py` (needs ffmpeg).

Backups are created and restored from *Settings*; they can be taken while the service runs.
