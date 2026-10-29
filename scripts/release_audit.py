"""Audit Git candidates locally. Reports paths/rules, never matching secret values."""

import argparse
import hashlib
import io
import json
import re
import subprocess
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent


def audit(terms_file=None, expected_remote=None):
    candidates = (
        subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
        )
        .decode("utf-8")
        .split("\0")
    )
    candidates = sorted(set(n for n in candidates if n))
    terms = []
    if terms_file:
        terms = [
            s.strip().casefold()
            for s in Path(terms_file).read_text(encoding="utf-8").splitlines()
            if s.strip()
        ]
    findings = []
    manifest_path = ROOT / "demo/synthetic/manifest.json"
    manifest = json.loads(manifest_path.read_text())["files"] if manifest_path.exists() else {}
    secrets = {
        "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "service-token": re.compile(
            r"(?:gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16}|sk_live_[A-Za-z0-9]{20,})"
        ),
        "personal-identifier": re.compile(
            r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"
        ),
    }
    allowed = {
        ".py",
        ".js",
        ".tsx",
        ".ts",
        ".css",
        ".rs",
        ".toml",
        ".md",
        ".json",
        ".txt",
        ".yml",
        ".yaml",
        ".html",
        ".svg",
        ".lock",
        ".example",
        ".ps1",
    }
    for name in candidates:
        p = ROOT / name
        if not p.exists() or p.is_dir():
            continue
        if p.is_symlink() or p.stat().st_nlink > 1:
            findings.append({"path": name, "rule": "filesystem-link"})
            continue
        if any(
            part in {".venv", ".runtime", "node_modules", "target", "dist"}
            for part in p.relative_to(ROOT).parts
        ):
            findings.append({"path": name, "rule": "runtime-or-vendored-artifact"})
        raw = p.read_bytes()
        text = ""
        if p.suffix in {".png", ".jpg", ".jpeg", ".ico"}:
            if not (
                name.startswith("demo/synthetic/")
                or name.startswith("docs/screenshots/")
                or name in {"src-tauri/icons/icon.ico", "src-tauri/icons/icon.png"}
            ):
                findings.append({"path": name, "rule": "unapproved-image-location"})
            with Image.open(io.BytesIO(raw)) as im:
                if im.getexif():
                    findings.append({"path": name, "rule": "image-exif-metadata"})
                text = json.dumps(im.info, default=str)
            if (
                name.startswith("demo/synthetic/")
                and manifest.get(p.name) != hashlib.sha256(raw).hexdigest()
            ):
                findings.append({"path": name, "rule": "synthetic-manifest-mismatch"})
        elif p.suffix == ".pdf":
            if (
                not name.startswith("demo/synthetic/")
                or manifest.get(p.name) != hashlib.sha256(raw).hexdigest()
            ):
                findings.append({"path": name, "rule": "unverified-pdf"})
            reader = PdfReader(io.BytesIO(raw))
            text = (
                str(reader.metadata)
                + "\n"
                + "\n".join(page.extract_text() or "" for page in reader.pages)
            )
            if reader.attachments:
                findings.append({"path": name, "rule": "embedded-pdf-attachment"})
        elif p.suffix in allowed or p.name in {
            ".gitignore",
            ".gitattributes",
            ".pre-commit-config.yaml",
        }:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                findings.append({"path": name, "rule": "non-utf8-source"})
        else:
            findings.append({"path": name, "rule": "unreviewed-file-type"})
        if (
            name.startswith("demo/synthetic/")
            and p.name != "manifest.json"
            and manifest.get(p.name) != hashlib.sha256(raw).hexdigest()
        ):
            findings.append({"path": name, "rule": "synthetic-manifest-mismatch"})
        for rule, pattern in secrets.items():
            if pattern.search(text):
                findings.append({"path": name, "rule": rule})
        if terms and any(term in (name + "\n" + text).casefold() for term in terms):
            findings.append({"path": name, "rule": "private-denylist-match"})
        if p.suffix in {
            ".py",
            ".ts",
            ".tsx",
            ".rs",
            ".toml",
            ".json",
            ".md",
            ".yml",
            ".html",
            ".css",
        } and re.search(r"[A-Z]:[\\/]+Users[\\/]", text):
            findings.append({"path": name, "rule": "absolute-user-path"})
    remotes = subprocess.check_output(["git", "remote"], cwd=ROOT).decode().split()
    for remote in remotes:
        urls = (
            subprocess.check_output(["git", "remote", "get-url", "--all", remote], cwd=ROOT)
            .decode()
            .splitlines()
        )
        push_urls = (
            subprocess.check_output(
                ["git", "remote", "get-url", "--push", "--all", remote], cwd=ROOT
            )
            .decode()
            .splitlines()
        )
        if not expected_remote or any(
            url.rstrip("/").removesuffix(".git") != expected_remote.rstrip("/").removesuffix(".git")
            for url in urls + push_urls
        ):
            findings.append({"path": ".git/config", "rule": "unapproved-remote"})
    staged_manifest = subprocess.run(
        ["git", "show", ":demo/synthetic/manifest.json"], cwd=ROOT, capture_output=True
    )
    staged_checked = False
    if staged_manifest.returncode == 0:
        staged_checked = True
        for name, digest in json.loads(staged_manifest.stdout)["files"].items():
            blob = subprocess.run(
                ["git", "show", ":demo/synthetic/" + name], cwd=ROOT, capture_output=True
            )
            if blob.returncode or hashlib.sha256(blob.stdout).hexdigest() != digest:
                findings.append(
                    {"path": "demo/synthetic/" + name, "rule": "staged-synthetic-hash-mismatch"}
                )
    return {
        "candidate_files": len(candidates),
        "findings": findings,
        "private_terms_applied": bool(terms),
        "staged_synthetic_hashes_checked": staged_checked,
        "limits": "Heuristic scan, not proof of legal clearance or absence of all personal data. Screenshot pixel review is manual.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--terms-file", help="Private denylist outside the repository")
    parser.add_argument(
        "--expected-remote", help="Exact repository URL approved for this publication"
    )
    args = parser.parse_args()
    result = audit(args.terms_file, args.expected_remote)
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result["findings"]))
