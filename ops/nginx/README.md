# Axelio security and performance snippets

The API also sets its own defensive headers. Nginx must set the shared policy
for static frontend responses, redirects and proxy-generated error responses.

Install the tracked snippet once (the deploy workflow keeps the installed copy
up to date afterward):

```bash
sudo install -D -m 0644 \
  /var/www/axelio/prod/repo/ops/nginx/axelio-security-headers.conf \
  /etc/nginx/snippets/axelio-security-headers.conf
sudo install -D -m 0644 \
  /var/www/axelio/prod/repo/ops/nginx/axelio-performance.conf \
  /etc/nginx/snippets/axelio-performance.conf
```

Add this line inside every Axelio `server` block:

```nginx
include /etc/nginx/snippets/axelio-security-headers.conf;
include /etc/nginx/snippets/axelio-performance.conf;
```

Validate before reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
curl -sSI https://app.axelio.ru/ | grep -Ei \
  'strict-transport-security|content-security-policy|x-content-type-options|referrer-policy|permissions-policy'
curl -sSI https://api.axelio.ru/health | grep -Ei \
  'strict-transport-security|content-security-policy|x-frame-options|x-content-type-options|referrer-policy|permissions-policy'
curl --compressed -sS -D - -o /dev/null https://app.axelio.ru/app.js | \
  grep -Ei 'content-encoding: gzip|etag:'
```

The frontend CSP allows framing only by Telegram Web. Do not add
`X-Frame-Options: DENY` to app responses: Telegram web clients load Mini Apps
in an iframe. FastAPI keeps `X-Frame-Options: DENY` for API responses.

Do not replace an unknown server configuration automatically. Adding the
`include` lines are a one-time reviewed operations change; afterward the
tracked snippets are the canonical source for both dev and production, and
every deploy validates Nginx before reloading it.
