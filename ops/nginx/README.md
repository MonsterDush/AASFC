# Axelio security headers

The API also sets its own defensive headers. Nginx must set the shared policy
for static frontend responses, redirects and proxy-generated error responses.

Install the tracked snippet once (the deploy workflow keeps the installed copy
up to date afterward):

```bash
sudo install -D -m 0644 \
  /var/www/axelio/prod/repo/ops/nginx/axelio-security-headers.conf \
  /etc/nginx/snippets/axelio-security-headers.conf
```

Add this line inside every Axelio `server` block:

```nginx
include /etc/nginx/snippets/axelio-security-headers.conf;
```

Validate before reload:

```bash
sudo nginx -t
sudo systemctl reload nginx
curl -sSI https://app.axelio.ru/ | grep -Ei \
  'strict-transport-security|content-security-policy|x-frame-options|x-content-type-options|referrer-policy|permissions-policy'
curl -sSI https://api.axelio.ru/health | grep -Ei \
  'strict-transport-security|content-security-policy|x-frame-options|x-content-type-options|referrer-policy|permissions-policy'
```

Do not replace an unknown server configuration automatically. Adding the
`include` is a one-time reviewed operations change; afterward the tracked
snippet is the canonical source for both dev and production, and every deploy
validates Nginx before reloading it.
