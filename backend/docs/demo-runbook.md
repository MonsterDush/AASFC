# Axelio DEMO Runbook

## Что проверять после bootstrap DEMO
1. В `venues` есть одно заведение с `is_demo = true`.
2. У demo venue заполнены `demo_reference_year` и `demo_reference_month`.
3. В `users` есть demo-пользователи с `is_demo_user = true`.
4. Есть как минимум:
   - `demo_owner`
   - `demo_staff`
   - дополнительные demo-сотрудники для графика и начислений
5. В `venue_members` demo-сотрудники привязаны к demo venue.
6. В demo month есть:
   - смены
   - закрытые отчёты
   - расходы
   - начисления
   - сводка
7. Если запуск был с `--export-fixture-after`, появился fixture-файл.

## Команда bootstrap
```bash
cd /var/www/axelio/dev/repo/backend
source /var/www/axelio/dev/venv/bin/activate
python -m app.scripts.bootstrap_demo_data --make-public --export-fixture-after
```

## Команда bootstrap в конкретное venue
```bash
python -m app.scripts.bootstrap_demo_data --venue-id 123 --make-public --export-fixture-after
```

## Что проверять после включения public DEMO
1. Кнопка `Попробовать` на лендинге ведёт в DEMO.
2. Срабатывает `GET /auth/demo/start`.
3. Пользователь открывает приложение без обычной регистрации.
4. На всех DEMO-страницах видна компактная DEMO-панель.
5. В DEMO-панели работают:
   - переключение `Владелец / Персонал`
   - `На сайт`
   - CTA-кнопки
6. По умолчанию открывается подготовленный demo month.

## Что проверять после переключения persona
1. `POST /auth/demo/switch-persona` возвращает успех.
2. После переключения на `OWNER` доступны owner-экраны.
3. После переключения на `STAFF` доступны staff-экраны.
4. Навигация не остаётся на заведомо чужом экране.
5. DEMO-панель сохраняется после переключения.

## Что проверять по read-only защите
1. Любая попытка изменить данные в DEMO должна возвращать:
   - HTTP `403`
   - `error_code = DEMO_READONLY`
2. Frontend показывает понятный toast о пробном режиме.
3. В DEMO нельзя:
   - создавать
   - редактировать
   - удалять
   - архивировать
   - закрывать отчёты
   - менять настройки
4. Суперадмин в обычной сессии может редактировать demo venue без DEMO-ограничений.

## Что проверять по fixture export
1. Выполняется:
```bash
python -m app.scripts.export_demo_fixture
```
2. JSON-файл fixture создаётся без ошибок сериализации.
3. В fixture попадают:
   - venue
   - demo users
   - venue_members
   - shifts / assignments
   - reports / values
   - expenses
   - payroll
   - billing demo state
4. Если в данных есть поля времени, export не падает на `time is not JSON serializable`.

## Что проверять по fixture reset
1. Выполняется:
```bash
python -m app.scripts.reset_demo_fixture
```
2. DEMO-состояние откатывается к эталону.
3. После reset:
   - DEMO снова открывается
   - demo month заполнен
   - данные совпадают с fixture
4. Не остаются случайные записи, созданные после ручных тестов.

## Если DEMO не открывается с лендинга
1. Проверить, что работает `GET /auth/demo/start`.
2. Проверить, что у demo venue стоит `is_demo = true`.
3. Проверить, что существует public demo venue.
4. Проверить cookie / JWT после старта DEMO.
5. Проверить логи API:
   - dev: `sudo journalctl -u axelio-api-dev -n 100 --no-pager`
   - prod: `sudo journalctl -u axelio-api-prod -n 100 --no-pager`

## Если не грузится `app-venue`
1. Открыть browser console.
2. Проверить ошибки module import из `/app.js`.
3. Убедиться, что `app.js` экспортирует DEMO shared helpers:
   - `isDemoUiMode`
   - `coerceDemoMonth`
   - `coerceDemoDate`
   - `coerceDemoRange`
   - `applyDemoReadonlyCaps`
4. Проверить, что `getMyVenuePermissions(venueId)` не падает.
5. Проверить ответ `/me/venues/{venue_id}/permissions`.
6. Если фронт после деплоя странно ведёт себя только в браузере/mini app — сбросить кэш.

## Если DEMO-панель не отображается
1. Проверить, что в `/me` приходит:
   - `demo_mode`
   - `demo_persona`
   - `demo_access_mode`
   - `demo_reference_year`
   - `demo_reference_month`
2. Проверить, что фронт инициализирует banner на странице.
3. Проверить `styles.css` и demo-banner стили.
4. Проверить, не едет ли старый кэш фронта.

## Если переключение Owner / Staff не работает
1. Проверить `POST /auth/demo/switch-persona`.
2. Проверить, что persona реально меняется в DEMO-сессии.
3. Проверить, что после reload `/me` возвращает новую persona.
4. Проверить, что страницы не закэшировали старое состояние в sessionStorage/localStorage.

## Если DEMO не read-only
1. Проверить DEMO middleware / guard на backend.
2. Проверить, что mutation запрос действительно идёт в DEMO-сессии.
3. Проверить whitelist исключений:
   - `/auth/demo/switch-persona`
   - `/auth/demo/exit`
   - `/auth/logout`
4. Убедиться, что боевые mutation endpoints не обошли общий guard.

## Если bootstrap отрабатывает, но DEMO выглядит пустым
1. Проверить, что demo month совпадает с данными, которые были созданы.
2. Проверить, что owner/staff страницы открываются именно на demo month.
3. Проверить, что отчёты закрыты и попадают в агрегаты.
4. Проверить, что payroll был рассчитан на demo month.
5. При необходимости вручную донастроить данные через суперадмина и снова сделать export fixture.

## Если export fixture падает
1. Проверить traceback.
2. Если ошибка сериализации — проверить тип поля, которое попало в payload.
3. Убедиться, что сериализатор покрывает:
   - `datetime`
   - `date`
   - `time`
   - `Decimal`
4. После фикса повторить:
```bash
python -m app.scripts.export_demo_fixture
```

## Если reset fixture падает
1. Проверить, существует ли fixture-файл.
2. Проверить, что `DEMO_FIXTURE_PATH` указан корректно.
3. Проверить, что JSON не повреждён.
4. Проверить, что restore-логика умеет восстановить типы:
   - date
   - datetime
   - time
   - numeric fields

## Если после DEMO-изменений сломались обычные страницы
1. Проверить shared imports из `/app.js`.
2. Проверить, не импортирует ли какая-то страница несуществующий helper.
3. Прогнать:
```bash
node --check /var/www/axelio/dev/repo/frontend/app.js
```
4. При необходимости проверить конкретный файл:
```bash
node --check /var/www/axelio/dev/repo/frontend/owner-summary.js
```

## Полезные команды
- API dev:
```bash
sudo journalctl -u axelio-api-dev -f
```

- API prod:
```bash
sudo journalctl -u axelio-api-prod -f
```

- Проверка миграций:
```bash
cd /var/www/axelio/dev/repo/backend
source /var/www/axelio/dev/venv/bin/activate
alembic heads
alembic upgrade head
```

- Ручной export fixture:
```bash
python -m app.scripts.export_demo_fixture
```

- Ручной reset fixture:
```bash
python -m app.scripts.reset_demo_fixture
```

- Ручной bootstrap DEMO:
```bash
python -m app.scripts.bootstrap_demo_data --make-public --export-fixture-after
```

## Минимальный smoke test после деплоя
1. Открыть DEMO с лендинга.
2. Проверить owner flow:
   - `app-venue`
   - `owner-summary`
   - `owner-expenses`
   - `owner-payroll`
3. Проверить owner advanced flow:
   - `owner-turnover`
   - `owner-finance-ledger`
   - `owner-day-economics`
4. Переключиться в staff.
5. Проверить staff flow:
   - `staff-shifts`
   - `staff-salary`
   - `staff-report`
6. Нажать любое запрещённое действие и убедиться, что оно заблокировано.
7. Вернуться на сайт через DEMO-панель.
8. Если DEMO готов к показу — зафиксировать fixture заново.

## Когда обновлять fixture
1. После заметного ручного улучшения demo-данных.
2. После изменения структуры данных DEMO.
3. После исправления bootstrap-сценария.
4. После правок, которые влияют на визуальную “продающую” часть DEMO.

## Кратко
Если что-то пошло не так:
1. Проверить `auth/demo/start`.
2. Проверить `app-venue`.
3. Проверить `/me` и `/permissions`.
4. Проверить DEMO guard.
5. Проверить bootstrap.
6. Проверить fixture export/reset.
7. Проверить кэш фронта.
