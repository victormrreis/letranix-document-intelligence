# Security model and publication gate

Evaluation is local and single-user. Use exclusively synthetic inputs. No application request sends document content, fields or decisions to an external provider. Dependency installation and advisory checks need network access; those tools receive package names/versions, not workspace documents.

Controls include loopback binding, Host validation, same-origin checks, an ephemeral browser session token, no CORS grants, generated storage IDs, parameterized SQL, SHA-256 deduplication, file/text/page/image limits, attachment downloads, restrictive browser headers, transactional state checks and explicit integration authorization. React renders extracted strings as text; HTML content is never injected.

Limitations: storage is unencrypted; the OS user can edit the database and audit records; any software running as that user can obtain a local session. The reviewer label is not authenticated. Parsers and OCR execute in the server process, without sandbox or hard CPU/memory deadline. Request bodies are bounded before multipart parsing, including chunked transfers; file content has a separate 10 MiB limit. Do not expose the service to a network or process hostile files. One process per workspace is supported.

Before publication run tests, static analysis, dependency advisories, Gitleaks, local heuristic scans with a private external denylist, manual image/PDF inspection, Git history and staged-file review. `scripts/release_audit.py` examines only Git candidates, rejects unexpected binary types and links, verifies fixture hashes, checks PDF attachments/image metadata, and reports rules without printing matched secret values. It cannot prove absence of all personal data or establish ownership.

Operational records, databases, logs, environments, caches, trained models, build output and agent transcripts are excluded. A private investigation report must remain outside the repository. Do not add denylist terms that disclose private organizations to versioned files.

This source-only portfolio preview was explicitly authorized on 2026-10-29. It does not grant an open-source license or establish legal clearance. New code alone does not remove ownership questions. Broader redistribution, third-party package/model notices and installer distribution require separate review before bundling dependencies.

## Desktop dependency finding

The Rust lockfile audit against OSV reported `block-buffer 0.10.4` / [GHSA-qwgh-2vcv-g2f7](https://github.com/advisories/GHSA-qwgh-2vcv-g2f7). It is reached through `digest → sha2 → tauri-codegen → tauri-macros`, a build dependency chain. Upstream reports a fix at 0.12.1, outside the current 0.10 dependency constraint. No unreviewed dependency patch or false clean result was substituted. Desktop distribution remains blocked pending compatible upstream remediation or a reviewed mitigation.

The all-platform lockfile additionally reports [glib unsoundness](https://rustsec.org/advisories/RUSTSEC-2024-0429.html) and [unmaintained proc-macro-error](https://rustsec.org/advisories/RUSTSEC-2024-0370.html); `cargo tree --target x86_64-pc-windows-msvc -i` returned no matching active Windows dependency for those two crates. Cross-platform distribution requires its own review. The tested browser application does not execute Rust dependencies.
