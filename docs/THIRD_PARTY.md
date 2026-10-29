# Dependency provenance and rights review

No open-source license is assigned to this application's new source. Ownership and distribution conditions require final review. The existence of independently written code does not settle employment or other rights questions. The owner authorized this source-only portfolio preview and its update with independently written code on 2026-10-29; that authorization does not grant an open-source license or certify legal clearance.

Dependencies are installed from public package registries into a new local environment. They are referenced through requirements, npm and Cargo lockfiles; package source trees, OCR weights, font files and runtime environments are not vendored into this repository.

| Component | Validated version | Declared license |
|---|---|---|
| FastAPI | 0.162.0 | MIT |
| Uvicorn | 0.54.0 | BSD-3-Clause |
| Pillow | 13.0.0 | MIT-CMU |
| pypdf | 6.21.4 | BSD-3-Clause |
| pypdfium2 (PDFium binary) | 5.14.0 | Apache-2.0 / BSD-3-Clause (PDFium) |
| python-multipart | 0.0.32 | Apache-2.0 |
| rapidocr-onnxruntime | 1.4.4 | Apache-2.0 |
| ONNX Runtime | 1.31.1 | MIT |
| React / React DOM | 19.3.1 | MIT |
| Lucide React | 0.468.0 | ISC |
| TypeScript | 5.9.3 | Apache-2.0 |
| Vite | 7.3.7 | MIT |
| eslint-plugin-react-hooks (dev) | 7.x | MIT |
| Playwright (dev) | 1.x | Apache-2.0 |
| Tauri | Cargo.lock | MIT OR Apache-2.0 |

Full installed Python and npm metadata inventories are in `python-dependencies.json` and `node-dependencies.json`; Rust dependencies are pinned in `src-tauri/Cargo.lock`. Declared package metadata is evidence, not a substitute for reviewing upstream LICENSE/NOTICE obligations before bundling. Python wheels can include separately licensed native libraries; installers require a further binary/notices review.

The [version-specific RapidOCR package metadata](https://pypi.org/project/rapidocr-onnxruntime/1.4.4/) declares Apache-2.0. OCR code and model weights have distinct provenance. The [upstream model licensing notice](https://rapidai.github.io/RapidOCRDocs/main/en/model_licenses/) distinguishes those rights and limits its listed model coverage; older bundled models need their own version-specific provenance review before redistribution. This repository does not redistribute ONNX assets. Local evaluation used the models installed with the official dependency, not operational caches or adjusted weights. A future standalone bundle must preserve applicable notices and establish coverage for each exact model hash.

pypdf's [official metadata](https://pypi.org/project/pypdf/) declares BSD-3-Clause. The native demo PDF is generated with code in `letranix.demo`, uses a PDF base font reference and embeds no font file. Raster fixtures render text using an installed Windows font, with a Pillow fallback. No OS font file is copied. See Microsoft's [font usage FAQ](https://learn.microsoft.com/en-us/typography/fonts/font-faq) for the distinction between rendered graphics and font redistribution. The geometric LETRANIX mark was authored as SVG in this project; desktop icons are generated from it. The name itself has not undergone a trademark availability search and no third-party endorsement is claimed.

Remaining licensing and distribution review: application ownership and broader distribution conditions, chosen application license, name availability, all transitive notices and any future bundled native/model assets. Do not infer legal release from dependency scanners or this inventory.

pypdfium2 was added in 0.2 to render scanned PDF pages for OCR and page previews; its wheel ships a PDFium binary under Apache-2.0/BSD-3-Clause notices that must be preserved if a bundle is ever distributed. The npm inventory includes one CC-BY-4.0 package (`caniuse-lite`, build-time browser data, not shipped in the bundle). The animated demo and screenshots in `docs/assets` were produced by this project's automated tests from generated synthetic documents.
