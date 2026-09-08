# Plans and percent tiers QA

Проверено локально 7 сентября 2026 года в ветке `codex/complete-names-intervals`.

## Browser E2E

Команда: `tools/e2e-local.sh browser`

Результат: 13 сценариев прошли на desktop 1440×900 и mobile 375×812. Новый сценарий:

1. открывает «Планы департаментов» за март 2035 года;
2. проверяет 31 календарную дату;
3. заполняет разные значения Пн–Вс и применяет их ко всему месяцу;
4. вручную меняет план одной даты;
5. подтверждает, что месячный план остаётся независимым;
6. создаёт профиль с базовыми 3% и ступенями 100% → 4%, 110% → 5%, 120% → 6%;
7. повторно открывает редактор, меняет последнюю ставку на 6,5% и проверяет сохранённый API-контракт;
8. удаляет временный профиль и компонент.

Во всех 13 сценариях `scrollWidth` равен ширине viewport. Регрессия локальных имён, нескольких должностей, фильтрации интервалов и сохранения существующих назначений также прошла.

## Backend и миграции

- `DATABASE_URL=sqlite:// .venv/bin/python -m unittest discover -s test -q` — 508 тестов, `OK`;
- `.venv/bin/python -m ruff check app test` — без ошибок;
- `.venv/bin/python -m ruff format --check app test` — 331 файл отформатирован;
- `tools/e2e-local.sh migration-smoke` — PostgreSQL `upgrade → downgrade → upgrade`, head `d3e5f7a9b1c2`;
- `git diff --check` — без ошибок.

Покрыты 28/29/30/31 день, CLOSED-only факт, день без отчёта и закрытый нулевой день, bulk с обоими режимами перезаписи и устаревшим preview token, ручной override, отсутствие плана, точные границы 100/110/120%, превышение максимальной ступени, планы заведения и нескольких департаментов, дневной и месячный источник, KPI, `REPLACE_ALL`, `EXCESS_ONLY`, minimum guarantee, maximum cap, legacy single boost и удаление ступеней без удаления компонента.

## Frontend contracts

- `pnpm test:frontend-quality` — ESLint, Prettier и TypeScript прошли;
- `pnpm test:i18n` — 4675 русских строк, английский каталог полный, 1704 semantic rules прошли;
- `pnpm test:budgets` — 186 файлов в пределах бюджета;
- отдельные facade, style, pay-profile split, staff-shifts split, finance и analytics contracts прошли.

## Артефакты

- `department-plans-desktop.png`
- `department-plans-mobile.png`
- `percent-tier-editor-desktop.png`
- `percent-tier-editor-mobile.png`

Расчёты и UI проверялись только в локальном E2E-окружении. Публикация и production deploy не выполнялись.
