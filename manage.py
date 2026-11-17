#!/usr/bin/env python3
"""List, copy and package explicitly listed Workhub module source files."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_MODULE_BYTES = 40 * 1024 * 1024
MODULE_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
PRIVATE_NAMES = {".env", "llm.json", "glm.json", "credentials.json", "session.json", "config.json",
                 "module-install.json", "library.json", "atlas.json", "frontier.json", "frontier-last-run.json", "last-run.json", "latest.json", "最新日报.md",
                 "previous.json", "delta.json", "增量简报.md", "seen-index.json", "story-history.json", "ai-analysis.json",
                 ".collection-state.json", ".collection-mode.json"}
EXCLUDED_PARTS = {"data", "logs", "runtime", "exports", "reports", "__pycache__", "node_modules",
                  "tests", "test", "__tests__", "test-fixtures"}
ALLOWED_SUFFIXES = {".py", ".html", ".css", ".js", ".json", ".md", ".txt", ".svg"}
PRIVATE_PATH = re.compile(r"(?:/(?:Users|home)/[A-Za-z0-9._-]+/|[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/])")
PROVIDER_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{25,}|sk-(?:proj-|ant-api\d*-)?[A-Za-z0-9_-]{24,}|xox[baprs]-[A-Za-z0-9-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})\b")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")
CREDENTIAL_URL = re.compile(r"https?://[^\s/:]+:[^\s/@]+@", re.I)
AUTOMATION_ID = re.compile(r"\bautomation-[0-9a-f]{8,}\b", re.I)


class ModuleError(ValueError):
    pass


def safe_relative(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value:
        raise ModuleError("module paths must be nonempty relative POSIX paths")
    path = PurePosixPath(value)
    if (path.is_absolute() or any(part in {".", ".."} or ":" in part for part in value.split("/"))
            or "" in value.split("/")):
        raise ModuleError("module paths cannot escape their root")
    return path


def regular_file(base: Path, relative: PurePosixPath) -> Path:
    current = base
    if base.is_symlink() or not base.is_dir():
        raise ModuleError("source root must be a real directory")
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError:
            raise ModuleError(f"missing source file: {relative.as_posix()}") from None
        if stat.S_ISLNK(mode):
            raise ModuleError(f"symbolic links are not allowed: {relative.as_posix()}")
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(mode):
            raise ModuleError(f"source parent is not a directory: {relative.as_posix()}")
    if not stat.S_ISREG(mode):
        raise ModuleError(f"special files are not allowed: {relative.as_posix()}")
    return current


def read_json(path: Path) -> dict:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ModuleError("metadata is too large")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ModuleError("invalid module metadata") from None
    if not isinstance(value, dict):
        raise ModuleError("module metadata must be an object")
    return value


def catalog() -> dict:
    value = read_json(regular_file(ROOT, PurePosixPath("catalog.json")))
    if value.get("schema_version") != 1 or not isinstance(value.get("modules"), list):
        raise ModuleError("unsupported catalog schema")
    ids = []
    for item in value["modules"]:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or not MODULE_ID.fullmatch(item["id"])):
            raise ModuleError("invalid catalog module id")
        ids.append(item["id"])
    if len(ids) != len(set(ids)):
        raise ModuleError("duplicate catalog module id")
    return value


def forbidden_source(relative: PurePosixPath) -> bool:
    parts = [part.lower() for part in relative.parts]
    name = parts[-1]
    return (any(part in EXCLUDED_PARTS or part.startswith(".") for part in parts)
            or name in PRIVATE_NAMES
            or name == "index.html"
            or re.fullmatch(r"(?:test_.*\.py|.*_test\.(?:py|go)|.*\.(?:test|spec)\..+)", name) is not None
            or Path(name).suffix not in ALLOWED_SUFFIXES)


def validate_content(raw: bytes, relative: PurePosixPath) -> None:
    if len(raw) > MAX_FILE_BYTES:
        raise ModuleError(f"source file exceeds size limit: {relative.as_posix()}")
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        raise ModuleError(f"source file must be UTF-8: {relative.as_posix()}") from None
    if raw.startswith(b"SQLite format 3\0") or any(pattern.search(text) for pattern in (
            PRIVATE_PATH, PROVIDER_TOKEN, PRIVATE_KEY, CREDENTIAL_URL, AUTOMATION_ID)):
        raise ModuleError(f"source requires privacy review: {relative.as_posix()}")


def load_module(module_id: str) -> tuple[dict, dict, list[tuple[str, bytes]]]:
    if not MODULE_ID.fullmatch(module_id):
        raise ModuleError("invalid module id")
    items = [item for item in catalog()["modules"] if item["id"] == module_id]
    if not items:
        raise ModuleError(f"unknown module: {module_id}")
    item = items[0]
    module_path = safe_relative(item.get("path"))
    if module_path.as_posix() != f"modules/{module_id}":
        raise ModuleError("module source must be in its catalog modules directory")
    manifest_path = safe_relative(f"{module_path.as_posix()}/module.json")
    manifest_file = regular_file(ROOT, manifest_path)
    source = manifest_file.parent
    manifest = read_json(manifest_file)
    if manifest.get("schema_version") != 1 or manifest.get("id") != module_id:
        raise ModuleError("manifest identity does not match the catalog")
    if (not isinstance(manifest.get("version"), str) or not manifest["version"].strip()
            or manifest["version"] != item.get("version")):
        raise ModuleError("manifest version does not match the catalog")
    names_by_language = manifest.get("name")
    if not isinstance(names_by_language, dict) or any(
            not isinstance(names_by_language.get(language), str) or not names_by_language[language].strip()
            for language in ("zh-CN", "en")):
        raise ModuleError("module requires Chinese and English names")
    names = manifest.get("files")
    if not isinstance(names, list) or not names or len(names) > 128 or any(not isinstance(name, str) for name in names):
        raise ModuleError("manifest requires an explicit file list of at most 128 files")
    if len(names) != len(set(names)) or "module.json" not in names:
        raise ModuleError("file list must be unique and include module.json")
    payload = []
    total = 0
    for name in sorted(names):
        relative = safe_relative(name)
        if forbidden_source(relative):
            raise ModuleError(f"test, private or runtime files cannot be distributed: {name}")
        file_path = regular_file(source, relative)
        if file_path.stat().st_size > MAX_FILE_BYTES:
            raise ModuleError(f"source file exceeds size limit: {name}")
        with file_path.open("rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
        validate_content(raw, relative)
        total += len(raw)
        if total > MAX_MODULE_BYTES:
            raise ModuleError("module exceeds total size limit")
        payload.append((relative.as_posix(), raw))
    return item, manifest, payload


def destination(value: str) -> Path:
    path = Path(value).expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise ModuleError("output already exists; choose a new output path")
    return path


def source_summary(module_id: str, manifest: dict, payload: list[tuple[str, bytes]]) -> dict:
    return {"id": module_id, "version": manifest["version"], "file_count": len(payload),
            "bytes": sum(len(raw) for _, raw in payload),
            "files": [{"path": name, "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in payload]}


def install(args: argparse.Namespace) -> dict:
    _, manifest, payload = load_module(args.module)
    target = destination(args.output)
    result = source_summary(args.module, manifest, payload)
    result.update(action="install", output=str(target), dry_run=args.dry_run)
    if args.dry_run:
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    # mkdir is exclusive: even an existing empty directory is never replaced.
    try:
        target.mkdir(mode=0o700)
    except FileExistsError:
        raise ModuleError("output already exists; choose a new output path") from None
    try:
        for name, raw in payload:
            file_path = target / name
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open("xb") as handle:
                handle.write(raw)
        receipt = dict(result, installed_at=datetime.now(timezone.utc).isoformat())
        (target / "module-install.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(target)
        raise
    return result


def package(args: argparse.Namespace) -> dict:
    _, manifest, payload = load_module(args.module)
    target = destination(args.output)
    if target.suffix.lower() != ".zip":
        raise ModuleError("package output must end in .zip")
    result = source_summary(args.module, manifest, payload)
    result.update(action="package", output=str(target), dry_run=args.dry_run)
    if args.dry_run:
        return result
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = target.open("xb")
    except FileExistsError:
        raise ModuleError("output already exists; choose a new output path") from None
    try:
        with handle, zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, raw in payload:
                entry = zipfile.ZipInfo(f"{args.module}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                entry.create_system = 3
                archive.writestr(entry, raw)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    result["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
    return result


def connect(args: argparse.Namespace) -> dict:
    _, manifest, _ = load_module(args.module)
    installed = Path(args.installed).expanduser().absolute()
    local_manifest = read_json(regular_file(installed, PurePosixPath("module.json")))
    if local_manifest.get("id") != args.module or local_manifest.get("schema_version") != 1:
        raise ModuleError("installed directory is not the selected module")
    site_entry = safe_relative(manifest.get("site", {}).get("entry", ""))
    site_url = getattr(args, "site_url", None)
    if site_url is not None:
        try:
            parsed = urlsplit(site_url)
            valid = (parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                     and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
                     and not any(ord(char) < 33 for char in site_url))
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ModuleError("site URL must be a loopback HTTP(S) address without credentials, query or fragment")
        site_arguments = ["--site-url", site_url]
    else:
        if manifest.get("site", {}).get("kind") == "server":
            raise ModuleError("start this server module explicitly, then connect with --site-url")
        regular_file(installed, site_entry)
        site_arguments = ["--site-dir", str(installed / site_entry.parent)]
    layout = manifest.get("site", {}).get("layout", "radar")
    if layout not in {"radar", "library", "brief"}:
        raise ModuleError("unsupported site layout")
    workhub = Path(args.workhub).expanduser().absolute()
    installer = regular_file(workhub, PurePosixPath("scripts/install.py"))
    command = [sys.executable, str(installer), "--project", str(installed), *site_arguments,
               "--site-name", manifest["name"]["zh-CN"], "--template", layout]
    result = {"action": "connect", "id": args.module, "dry_run": args.dry_run, "command": command,
              "note": "Connects the built site only; does not start collection, a server or an automation."}
    if not args.dry_run:
        completed = subprocess.run(command, check=False)
        if completed.returncode:
            raise ModuleError(f"Workhub installer failed with exit code {completed.returncode}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="list locally available modules; no network requests")
    for action in ("install", "package"):
        command = sub.add_parser(action, help="copy source into a new directory" if action == "install" else "create a source-only ZIP")
        command.add_argument("module")
        command.add_argument("--output", required=True)
        command.add_argument("--dry-run", action="store_true")
    command = sub.add_parser("connect", help="explicitly connect an already built site to a local Workhub checkout")
    command.add_argument("module")
    command.add_argument("--installed", required=True)
    command.add_argument("--workhub", required=True)
    command.add_argument("--site-url", help="connect an explicitly started loopback server instead of a static directory")
    command.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "list":
            result = {"schema_version": 1, "modules": catalog()["modules"]}
        else:
            result = {"install": install, "package": package, "connect": connect}[args.action](args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ModuleError, OSError, zipfile.BadZipFile) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
