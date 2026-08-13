# Russian and English localization

Axelio supports Russian (`ru`) and English (`en`). Russian source copy remains
the canonical authoring language; the browser applies the English catalog at
runtime. User-created content such as venue names, comments, category titles,
and employee names is not intentionally translated.

## Locale selection

The browser resolves the locale in this order:

1. the `lang=ru|en` URL parameter;
2. the `axelio.lang` local-storage preference;
3. the browser language;
4. Russian as the fallback.

For authenticated users, `/me` returns `preferred_locale`. The Settings page
persists changes through `PATCH /me/profile`, so the same locale is used on
other devices and for Telegram notifications. API requests and downloads also
send `Accept-Language`.

## Frontend catalog

- Runtime: `frontend/i18n.js` and `frontend/i18n-bootstrap.js`.
- English catalog: `frontend/locales/en.json`.
- Source collector: `tools/i18n-static-sources.mjs`.
- Coverage gate: `pnpm test:i18n`.
- Offline catalog builder: `tools/build_en_catalog_offline.py`.

After adding or changing Russian interface copy, update the English catalog and
run `pnpm test:i18n`. The builder uses an installed Argos Translate RU-to-EN
model only for missing strings. Existing entries are preserved and the curated
terminology overrides are reapplied on every run. Review customer-facing,
financial, and legal text manually before release.

## Backend channels

Telegram notifications choose the recipient's stored locale. Excel and CSV
financial exports choose the requesting user's locale. The frontend catalog
also covers user-facing backend validation and permission errors so they can be
shown in English without changing stable API error codes.

The English versions of the offer, privacy policy, and subscription terms carry
a notice that the Russian version governs if interpretations differ.
