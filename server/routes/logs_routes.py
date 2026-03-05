from __future__ import annotations

# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0
import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger("animaworks.routes.logs")

# Directories to search for log files
_LOG_SEARCH_DIRS = [
    Path.home() / ".animaworks" / "logs",
]


def _validate_filename(filename: str) -> None:
    """Reject filenames with path traversal attempts."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if filename.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid filename")


def _validate_file_ref(file_ref: str) -> None:
    """Validate relative log path or basename for safe resolution."""
    if not file_ref or not file_ref.strip():
        raise HTTPException(status_code=400, detail="Invalid file reference")
    candidate = Path(file_ref)
    if candidate.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid file reference")
    if any(part in ("..", "") for part in candidate.parts):
        raise HTTPException(status_code=400, detail="Invalid file reference")
    if file_ref.startswith("."):
        raise HTTPException(status_code=400, detail="Invalid file reference")


def _collect_log_files() -> list[dict]:
    """Collect log files from known directories."""
    files: list[dict] = []
    seen: set[str] = set()

    for log_dir in _LOG_SEARCH_DIRS:
        if not log_dir.exists():
            continue
        for log_file in log_dir.rglob("*.log"):
            if log_file.name in seen:
                continue
            seen.add(log_file.name)
            stat = log_file.stat()
            files.append(
                {
                    "name": log_file.name,
                    "path": str(log_file.relative_to(log_dir)),
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                }
            )

    # Sort by modification time descending
    files.sort(key=lambda f: f["modified"], reverse=True)
    return files


def _resolve_log_path(filename: str) -> Path | None:
    """Find a log file by relative path or filename in known log directories."""
    ref = Path(filename)
    matches: list[Path] = []

    for log_dir in _LOG_SEARCH_DIRS:
        root = log_dir.resolve()
        if not log_dir.exists():
            continue

        # Explicit relative path (supports nested paths from list endpoint)
        if len(ref.parts) > 1:
            candidate = (log_dir / ref).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.exists() and candidate.is_file():
                matches.append(candidate)
            continue

        # Backward-compatible basename resolution
        top_level = (log_dir / filename).resolve()
        try:
            top_level.relative_to(root)
        except ValueError:
            top_level = None
        if top_level and top_level.exists() and top_level.is_file():
            matches.append(top_level)

        for candidate in log_dir.rglob(filename):
            resolved = candidate.resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            if resolved.is_file():
                matches.append(resolved)

    if matches:
        unique = {str(path): path for path in matches}
        return max(unique.values(), key=lambda p: p.stat().st_mtime)
    return None


def create_logs_router() -> APIRouter:
    router = APIRouter()

    @router.get("/system/logs")
    async def list_logs(request: Request):
        """List available log files."""
        return {"files": _collect_log_files()}

    @router.get("/system/logs/stream")
    async def stream_logs(
        request: Request,
        file: str = Query(default="animaworks.log"),
    ):
        """SSE endpoint for real-time log streaming (tail -f style)."""
        _validate_filename(file)
        log_path = _resolve_log_path(file)
        if log_path is None:
            raise HTTPException(status_code=404, detail=f"Log file not found: {file}")

        async def log_stream_generator():
            try:
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    # Seek to end
                    f.seek(0, 2)
                    while True:
                        line = f.readline()
                        if line:
                            yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
                        else:
                            await asyncio.sleep(0.5)
            except Exception as exc:
                yield f"data: {json.dumps({'error': str(exc)})}\n\n"

        return StreamingResponse(
            log_stream_generator(),
            media_type="text/event-stream",
        )

    @router.get("/system/logs/{filename}")
    async def read_log(
        request: Request,
        filename: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=5000),
    ):
        """Read log file content with pagination."""
        _validate_filename(filename)
        log_path = _resolve_log_path(filename)
        if log_path is None:
            raise HTTPException(status_code=404, detail=f"Log file not found: {filename}")

        try:
            all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read log: {exc}") from exc

        total_lines = len(all_lines)
        paginated = all_lines[offset : offset + limit]

        return {
            "filename": filename,
            "total_lines": total_lines,
            "offset": offset,
            "limit": limit,
            "lines": paginated,
        }

    @router.get("/system/logs/file/read")
    async def read_log_by_ref(
        request: Request,
        file: str = Query(..., min_length=1),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=5000),
    ):
        """Read log file by basename or relative path from list endpoint."""
        _validate_file_ref(file)
        log_path = _resolve_log_path(file)
        if log_path is None:
            raise HTTPException(status_code=404, detail=f"Log file not found: {file}")

        try:
            all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"Failed to read log: {exc}") from exc

        total_lines = len(all_lines)
        paginated = all_lines[offset : offset + limit]

        return {
            "filename": log_path.name,
            "path": file,
            "total_lines": total_lines,
            "offset": offset,
            "limit": limit,
            "lines": paginated,
        }

    return router
