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

The first release in each environment runs `activate-performance.sh`. It only
edits active configuration files for that release scope (`app/api.axelio.ru`
in production or `app-dev/api-dev.axelio.ru` in development) that already use the
tracked security snippet. Before editing it creates a backup under
`/var/backups/axelio/nginx`, refuses partial/ambiguous activation, and restores
the original files if `nginx -t` fails.

The resulting lines inside every matched Axelio `server` block are:

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

The frontend CSP allows framing by Telegram Web and the explicitly listed
Yandex Metrica viewers used for Session Replay and behavior maps. Do not add
`X-Frame-Options: DENY` to app responses: Telegram web clients load Mini Apps
in an iframe, while Metrica needs its documented frame and WebSocket sources.
FastAPI keeps `X-Frame-Options: DENY` for API responses.

Do not replace an unknown server configuration automatically. The activator
uses the existing Axelio security include as its reviewed insertion marker;
configs without that marker are deliberately left untouched. After the first
activation, the tracked snippets are the canonical source and every deploy
validates Nginx before reloading it.
