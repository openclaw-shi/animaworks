from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

_IMAGE_PATH_RE = re.compile(
    r"(?:assets|attachments)/[A-Za-z0-9._/\-]+\.(?:png|jpe?g|gif|webp)",
    re.IGNORECASE,
)
_IMAGE_EXT_RE = re.compile(r"\.(?:png|jpe?g|gif|webp)(?:$|\?)", re.IGNORECASE)
_MAX_ARTIFACTS_PER_RESPONSE = 5
_ALLOWED_SEARCHED_IMAGE_HOSTS = {
    "cdn.search.brave.com",
    "images.unsplash.com",
    "images.pexels.com",
    "upload.wikimedia.org",
}
_PATH_KEYS = {"path", "file", "filepath", "asset_path"}
_URL_KEYS = {"url", "image_url", "thumbnail", "src"}


def extract_image_artifacts_from_tool_records(
    tool_call_records: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    """Extract normalized image artifacts from tool call records."""
    if not tool_call_records:
        return []

    artifacts: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def _append(*, tool_name: str, path: str = "", url: str = "", source: str) -> None:
        if len(artifacts) >= _MAX_ARTIFACTS_PER_RESPONSE:
            return
        clean_path = path.strip()
        clean_url = url.strip()
        if not clean_path and not clean_url:
            return
        trust = "trusted" if source == "generated" else "untrusted"
        key = (source, clean_path, clean_url)
        if key in seen:
            return
        seen.add(key)
        item: dict[str, str] = {
            "type": "image",
            "source": source,
            "trust": trust,
            "provider": tool_name or "unknown",
        }
        if clean_path:
            item["path"] = clean_path
        if clean_url:
            item["url"] = clean_url
        artifacts.append(item)

    def _is_allowed_searched_url(value: str) -> bool:
        if not value.startswith("https://"):
            return False
        if not _IMAGE_EXT_RE.search(value):
            return False
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        return any(host == d or host.endswith(f".{d}") for d in _ALLOWED_SEARCHED_IMAGE_HOSTS)

    def _walk(value: Any, tool_name: str) -> None:
        if len(artifacts) >= _MAX_ARTIFACTS_PER_RESPONSE:
            return
        if isinstance(value, dict):
            for key, val in value.items():
                key_l = str(key).lower()
                if isinstance(val, str):
                    if key_l in _PATH_KEYS:
                        if _IMAGE_PATH_RE.search(val):
                            _append(tool_name=tool_name, path=val, source="generated")
                    elif key_l in _URL_KEYS:
                        if _is_allowed_searched_url(val):
                            _append(tool_name=tool_name, url=val, source="searched")
                else:
                    _walk(val, tool_name)
            return
        if isinstance(value, list):
            for v in value:
                _walk(v, tool_name)
            return
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    parsed = json.loads(stripped)
                    _walk(parsed, tool_name)
                except json.JSONDecodeError:
                    return

    for record in tool_call_records:
        tool_name = str(record.get("tool_name", ""))
        result_summary = record.get("result_summary", "")
        _walk(result_summary, tool_name)
        if tool_name == "image_gen":
            for m in _IMAGE_PATH_RE.finditer(str(result_summary)):
                _append(tool_name=tool_name, path=m.group(0), source="generated")

    return artifacts
