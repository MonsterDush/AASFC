from __future__ import annotations

from fastapi import Request

from app.settings import settings


def resolve_client_ip(request: Request) -> str:
    peer_ip = str(request.client.host if request.client else "").strip() or "unknown"
    if peer_ip not in settings.trusted_proxy_ips():
        return peer_ip

    forwarded = str(request.headers.get("x-forwarded-for") or "").strip()
    if forwarded:
        client_ip = forwarded.split(",", 1)[0].strip()
        if client_ip:
            return client_ip

    real_ip = str(request.headers.get("x-real-ip") or "").strip()
    return real_ip or peer_ip
