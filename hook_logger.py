#!/usr/bin/env python3
"""Write privacy-minimized Claude hook events for the behavior harness.

The hook deliberately prints nothing. Hook stdout can enter model context for
some events, so observability must remain out-of-band.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_PREVIEW = 500


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def sha256_file(path: Path) -> str | None:
    try:
        if path.is_file() and not path.is_symlink():
            return sha256_bytes(path.read_bytes())
    except OSError:
        pass
    return None


def logical_path(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw:
        return None
    candidate = Path(raw).expanduser().resolve(strict=False)
    for environment, label in (
        ("GUARDPACK_PLUGIN_ROOT", "pack"),
        ("GUARDPACK_CONFIG_ROOT", "config"),
        ("GUARDPACK_WORK_ROOT", "workspace"),
    ):
        base_raw = os.environ.get(environment)
        if not base_raw:
            continue
        base = Path(base_raw).expanduser().resolve(strict=False)
        try:
            relative = candidate.relative_to(base)
        except ValueError:
            continue
        if label == "config":
            parts = relative.parts
            if len(parts) >= 4 and parts[:2] == ("guardpack", "versions"):
                relative = Path(*parts[3:])
                label = "pack"
        return f"{label}/{relative.as_posix()}"
    return f"external/{candidate.name}"


def preview(value: Any) -> dict[str, Any]:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    except (TypeError, ValueError):
        encoded = repr(value).encode("utf-8", errors="replace")
    text = encoded.decode("utf-8", errors="replace")
    return {
        "sha256": sha256_bytes(encoded),
        "bytes": len(encoded),
        "preview": text[:MAX_PREVIEW],
        "truncated": len(text) > MAX_PREVIEW,
    }


def selected_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_name = payload.get("hook_event_name", "unknown")
    selected: dict[str, Any] = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "hook_event_name": event_name,
        "session_id": payload.get("session_id"),
        "permission_mode": payload.get("permission_mode"),
        "cwd": logical_path(payload.get("cwd")),
    }
    if event_name == "InstructionsLoaded":
        file_path = payload.get("file_path")
        selected.update(
            {
                "file_path": logical_path(file_path),
                "file_sha256": sha256_file(Path(file_path)) if isinstance(file_path, str) else None,
                "memory_type": payload.get("memory_type"),
                "load_reason": payload.get("load_reason"),
                "parent_file_path": logical_path(payload.get("parent_file_path")),
                "trigger_file_path": logical_path(payload.get("trigger_file_path")),
            }
        )
    if "tool_name" in payload:
        selected["tool_name"] = payload.get("tool_name")
    if "tool_use_id" in payload:
        selected["tool_use_id"] = payload.get("tool_use_id")
    for field in (
        "tool_input",
        "tool_response",
        "permission_suggestions",
        "decision",
        "reason",
        "error",
    ):
        if field in payload:
            selected[field] = preview(payload[field])
    return selected


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    body = (json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, body)
    finally:
        os.close(descriptor)


def main() -> int:
    audit_dir = os.environ.get("GUARDPACK_AUDIT_DIR")
    if not audit_dir:
        return 0
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        append_event(Path(audit_dir) / "hook-events.jsonl", selected_event(payload))
    except Exception as error:  # A logger failure must never alter model behavior.
        try:
            append_event(
                Path(audit_dir) / "hook-errors.jsonl",
                {
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "error_type": type(error).__name__,
                    "error": str(error)[:MAX_PREVIEW],
                },
            )
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
