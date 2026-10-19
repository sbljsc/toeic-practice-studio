"""Write-path protection: localhost Host and same-origin Origin validation.

Local CLI tools legitimately send no Origin; browsers always send one for
state-changing requests, so a foreign Origin is rejected while a missing
Origin is allowed for local non-browser callers.
"""

import ipaddress
from urllib.parse import urlsplit

from fastapi import Request

from .errors import forbidden


def _host_is_local(host: str, allow_test_host: bool = False) -> bool:
    try:
        name = (urlsplit("//" + host).hostname or "").lower()
    except ValueError:
        return False
    if not name:
        return False
    if name == "testserver" and allow_test_host:
        return True
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def validate_write_request(request: Request) -> None:
    host = request.headers.get("host", "")
    allow_test_host = getattr(request.app.state, "allow_test_host", False)
    if not _host_is_local(host, allow_test_host):
        raise forbidden("仅允许本机访问：Host 必须指向 127.0.0.1/localhost。", "foreign_host")
    origin = request.headers.get("origin")
    if origin is None:
        return
    try:
        parsed = urlsplit(origin)
    except ValueError as exc:
        raise forbidden("非法的 Origin 头。", "foreign_origin") from exc
    if parsed.scheme not in ("http", "https") or not _host_is_local(parsed.netloc, allow_test_host):
        raise forbidden("写操作被拒绝：Origin 不是本机来源。", "foreign_origin")
    # Same-origin: scheme, host and port must match the actual request target,
    # so a page served from an unrelated localhost port cannot write.
    try:
        target = urlsplit(f"{request.url.scheme}://{host}")
        def normalized(value):
            hostname = (value.hostname or "").lower()
            try:
                hostname = ipaddress.ip_address(hostname).compressed
            except ValueError:
                pass
            port = value.port
            return (value.scheme.lower(), hostname,
                    port if port is not None else (443 if value.scheme == "https" else 80))
        same = normalized(parsed) == normalized(target)
        if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            same = False
    except ValueError:
        same = False
    if not same:
        raise forbidden("写操作被拒绝：Origin 与请求来源不一致。", "origin_mismatch")
