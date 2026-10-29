# Contributing during local review

Distribution and contribution licensing remain pending. This repository is an authorized source-only portfolio preview; it does not grant an open-source license or permission for broader redistribution. Do not add real documents, identifiers, credentials, datasets or operational logs to fixtures, issues, screenshots or tests.

Use Python 3.12 and Node 24. Run `npm ci`, install `requirements-lock.txt`, run `npm run build`, `npm run lint`, `python -m ruff check letranix tests scripts`, `python -m bandit -r letranix -q`, and `python -m pytest -q`. Use `python -m ruff format letranix tests scripts` for Python formatting and `npm run format` / `npm run format:check` for frontend formatting. Keep `package-lock.json` and the Python lockfile in sync with intentional dependency changes.

Install `pre-commit` in the virtual environment and run `pre-commit install` to enable local release and Gitleaks checks. The private denylist must also be run manually with `python scripts/release_audit.py --terms-file <private-path> --expected-remote https://github.com/victormrreis/letranix-document-intelligence.git`, because it must not be stored in this repository. Automated results do not replace staged-file review, provenance checks or binary inspection.
