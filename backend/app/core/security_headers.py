from __future__ import annotations

from starlette.responses import Response


API_CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'none'",
    ]
)


def security_headers(*, production: bool) -> dict[str, str]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    }
    if production:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        headers["Content-Security-Policy"] = API_CONTENT_SECURITY_POLICY
    return headers


def apply_security_headers(response: Response, *, production: bool) -> Response:
    for name, value in security_headers(production=production).items():
        if name not in response.headers:
            response.headers[name] = value
    return response
