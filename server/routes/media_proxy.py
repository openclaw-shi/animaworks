from __future__ import annotations

import ipaddress
import logging
import socket
import time
from collections import deque
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import Response

from core.config.models import MediaProxyConfig, load_config

logger = logging.getLogger("animaworks.routes.media_proxy")

_PROXY_ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}
_PROXY_DEFAULT_CONFIG = MediaProxyConfig()
_PROXY_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = {}


def _is_host_allowed(host: str, allowed_domains: list[str]) -> bool:
    host_l = host.lower()
    return any(host_l == d or host_l.endswith(f".{d}") for d in allowed_domains)


def _is_private_or_local_host(host: str) -> bool:
    """Detect localhost/private addresses including DNS-resolved hosts."""
    host_l = host.strip().lower()
    if host_l in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(host_l)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host_l, None)
    except socket.gaierror:
        return True
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return True
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return True
    return False


def _validate_proxy_target(url: str, proxy_config: MediaProxyConfig) -> str:
    """Validate proxy target URL and return normalized URL string."""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise HTTPException(status_code=400, detail="Only HTTPS URLs are allowed")
    host = parsed.hostname or ""
    if not host:
        raise HTTPException(status_code=400, detail="Invalid URL host")
    if _is_private_or_local_host(host):
        raise HTTPException(status_code=400, detail="Blocked private/local address")
    if proxy_config.mode == "allowlist" and not _is_host_allowed(host, proxy_config.allowed_domains):
        raise HTTPException(status_code=403, detail="Host is not in allowlist")
    return parsed.geturl()


def _get_media_proxy_config() -> MediaProxyConfig:
    """Return media proxy config with safe fallback on load error."""
    try:
        return load_config().server.media_proxy
    except Exception:
        logger.exception("Failed to load media_proxy config, using defaults")
        return _PROXY_DEFAULT_CONFIG


def _check_media_proxy_rate_limit(client_host: str, proxy_config: MediaProxyConfig) -> int | None:
    """Return retry-after seconds when rate-limited, otherwise None."""
    now_ts = time.monotonic()
    window_s = max(proxy_config.rate_limit_window_s, 1)
    max_requests = max(proxy_config.rate_limit_requests, 1)

    bucket = _PROXY_RATE_LIMIT_BUCKETS.setdefault(client_host, deque())
    while bucket and now_ts - bucket[0] >= window_s:
        bucket.popleft()

    if len(bucket) >= max_requests:
        retry_after = max(1, int(window_s - (now_ts - bucket[0])))
        return retry_after

    bucket.append(now_ts)

    stale_hosts = [host for host, q in _PROXY_RATE_LIMIT_BUCKETS.items() if not q or now_ts - q[-1] >= window_s]
    for host in stale_hosts:
        if host != client_host:
            _PROXY_RATE_LIMIT_BUCKETS.pop(host, None)
    return None


def _detect_image_content_type(body: bytes) -> str | None:
    """Detect image content type from magic bytes."""
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith(b"GIF87a") or body.startswith(b"GIF89a"):
        return "image/gif"
    if len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    return None


async def proxy_external_image(url: str, request: Request) -> Response:
    """Proxy external images for safer rendering in chat bubbles."""
    proxy_config = _get_media_proxy_config()
    current_url = _validate_proxy_target(url, proxy_config)

    client_host = request.client.host if request.client else "unknown"
    retry_after = _check_media_proxy_rate_limit(client_host, proxy_config)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many requests",
            headers={"Retry-After": str(retry_after)},
        )

    timeout = httpx.Timeout(proxy_config.timeout_read_s, connect=proxy_config.timeout_connect_s)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            upstream = None
            for _ in range(proxy_config.max_redirects + 1):
                upstream = await client.get(current_url)
                if upstream.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = upstream.headers.get("location")
                if not location:
                    raise HTTPException(status_code=502, detail="Invalid redirect location")
                redirected = urljoin(current_url, location)
                current_url = _validate_proxy_target(redirected, proxy_config)
            else:
                raise HTTPException(status_code=508, detail="Too many redirects")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch upstream image: {exc}") from exc

    if upstream is None:
        raise HTTPException(status_code=502, detail="Failed to fetch upstream image")
    if upstream.status_code >= 400:
        raise HTTPException(status_code=upstream.status_code, detail="Upstream image fetch failed")

    content_type = upstream.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type == "image/svg+xml":
        raise HTTPException(status_code=415, detail="Unsupported media type")
    if content_type and content_type not in _PROXY_ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported media type")

    declared_size = upstream.headers.get("content-length")
    if declared_size:
        try:
            if int(declared_size) > proxy_config.max_bytes:
                raise HTTPException(status_code=413, detail="Image too large")
        except ValueError:
            pass

    body = upstream.content
    if len(body) > proxy_config.max_bytes:
        raise HTTPException(status_code=413, detail="Image too large")
    detected_type = _detect_image_content_type(body)
    if not detected_type:
        raise HTTPException(status_code=415, detail="Invalid image payload")
    if content_type and detected_type != content_type:
        raise HTTPException(status_code=415, detail="Content type mismatch")

    return Response(
        content=body,
        media_type=detected_type,
        headers={
            "Cache-Control": "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )
