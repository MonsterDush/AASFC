# Axelio — шпаргалка VPS + Git

## 1. Подключение к VPS

```bash
ssh root@IP_СЕРВЕРА
```

Если используешь пользователя не root:

```bash
ssh username@IP_СЕРВЕРА
```

Перейти в dev-проект:

```bash
cd /var/www/axelio/dev/repo
```

Backend:

```bash
cd /var/www/axelio/dev/repo/backend
```

Frontend:

```bash
cd /var/www/axelio/dev/repo/frontend
```

Bot service:

```bash
cd /var/www/axelio/dev/repo/bot_service
```

---

## 2. Проверка сервисов

Dev API:

```bash
sudo systemctl status axelio-api-dev --no-pager
```

Dev bot:

```bash
sudo systemctl status axelio-bot-dev --no-pager
```

Рестарт API:

```bash
sudo systemctl restart axelio-api-dev
```

Рестарт бота:

```bash
sudo systemctl restart axelio-bot-dev
```

Рестарт обоих:

```bash
sudo systemctl restart axelio-api-dev
sudo systemctl restart axelio-bot-dev
sudo systemctl restart axelio-api-prod
sudo systemctl restart axelio-bot-prod
```

Проверить, что API живой:

```bash
curl http://127.0.0.1:9001/health
```

---

## 3. Логи

API live-логи:

```bash
journalctl -u axelio-api-dev -f
```

Bot live-логи:

```bash
journalctl -u axelio-bot-dev -f
```

Последние 100 строк API:

```bash
journalctl -u axelio-api-dev -n 100 --no-pager
```

Последние 100 строк бота:

```bash
journalctl -u axelio-bot-dev -n 100 --no-pager
```

Логи Nginx:

```bash
sudo tail -n 100 /var/log/nginx/error.log
```

Live-логи Nginx:

```bash
sudo tail -f /var/log/nginx/error.log
```

---

## 4. Nginx

Проверить конфиг:

```bash
sudo nginx -t
```

Перезагрузить Nginx:

```bash
sudo systemctl reload nginx
```

Полный рестарт:

```bash
sudo systemctl restart nginx
```

Список активных конфигов:

```bash
ls -la /etc/nginx/sites-enabled/
```

---

## 5. Порты и процессы

Посмотреть, кто слушает порты:

```bash
sudo ss -tulpn
```

Проверить конкретный порт, например API dev:

```bash
sudo ss -tulpn | grep 9001
```

Проверить bot service:

```bash
sudo ss -tulpn | grep 9010
```

Проверить Postgres dev:

```bash
sudo ss -tulpn | grep 55432
```

---

## 6. Проверка Telegram API с VPS

Полезно, если бот молчит:

```bash
curl -v https://api.telegram.org
```

Проверка через IPv4:

```bash
curl -4 -v https://api.telegram.org
```

Проверка через IPv6:

```bash
curl -6 -v https://api.telegram.org
```

Если `-4` работает, а обычный или `-6` висит — проблема IPv6.

---

## 7. ENV-файлы

Backend env:

```bash
nano /var/www/axelio/dev/repo/backend/.env
```

Bot env:

```bash
nano /var/www/axelio/dev/repo/bot_service/.env
```

После изменения `.env` обязательно:

```bash
sudo systemctl restart axelio-api-dev
sudo systemctl restart axelio-bot-dev
```

Сгенерировать внутренний секрет:

```bash
openssl rand -hex 32
```

---

## 8. Python backend

Перейти в backend:

```bash
cd /var/www/axelio/dev/repo/backend
```

Активировать venv:

```bash
source /var/www/axelio/dev/venv/bin/activate
```

Установить зависимости:

```bash
pip install -r requirements.txt
```

Проверить файл на синтаксис:

```bash
python -m py_compile app/routers/auth.py
```

Проверить несколько файлов:

```bash
python -m py_compile app/routers/me.py app/routers/venues.py app/routers/auth.py
```

---

## 9. Alembic / миграции

Перейти в backend:

```bash
cd /var/www/axelio/dev/repo/backend
source /var/www/axelio/dev/venv/bin/activate
```

Проверить текущую ревизию БД:

```bash
alembic current
```

Посмотреть головы миграций:

```bash
alembic heads
```

Посмотреть историю:

```bash
alembic history
```

Накатить миграции:

```bash
alembic upgrade head
```

Откатить одну миграцию назад:

```bash
alembic downgrade -1
```

Создать новую миграцию вручную:

```bash
alembic revision -m "описание_миграции"
```

---

## 10. Docker / Postgres

Посмотреть контейнеры:

```bash
docker ps
```

Посмотреть все, включая остановленные:

```bash
docker ps -a
```

Перезапустить контейнер БД:

```bash
docker restart axelio_db
```

Зайти в Postgres:

```bash
docker exec -it axelio_db psql -U axelio -d axelio
```

Внутри psql посмотреть таблицы:

```sql
\dt
```

Описание таблицы:

```sql
\d users
```

Выйти:

```sql
\q
```

---

## 11. Git: базовые команды

Проверить ветку и изменения:

```bash
git status
```

Посмотреть текущую ветку:

```bash
git branch --show-current
```

Посмотреть все ветки:

```bash
git branch -a
```

Получить свежие данные с GitHub:

```bash
git fetch --all
```

Подтянуть текущую ветку:

```bash
git pull
```

---

## 12. Git: работа с develop

Переключиться на develop:

```bash
git checkout develop
```

Подтянуть свежий develop:

```bash
git pull origin develop
```

Добавить все изменения:

```bash
git add .
```

Создать коммит:

```bash
git commit -m "fix: короткое описание"
```

Запушить develop:

```bash
git push origin develop
```

---

## 13. Git: влить develop в main

```bash
git checkout develop
git pull origin develop

git checkout main
git pull origin main

git merge develop --no-edit
git push origin main

git checkout develop
```

Вернуться в develop:

```bash
git checkout develop
```

---

## 14. Git: отмена локальных изменений

Посмотреть, что изменено:

```bash
git status
```

Отменить изменения в одном файле:

```bash
git checkout -- path/to/file
```

Отменить все локальные изменения:

```bash
git reset --hard
```

Удалить неотслеживаемые файлы:

```bash
git clean -fd
```

Осторожно: `reset --hard` и `clean -fd` удаляют локальные изменения.

---

## 15. Git: откат к конкретному коммиту

Посмотреть историю:

```bash
git log --oneline
```

Временно перейти на коммит:

```bash
git checkout HASH_КОММИТА
```

Откатить ветку жёстко до коммита:

```bash
git reset --hard HASH_КОММИТА
```

Запушить такой откат в develop:

```bash
git push origin develop --force
```

Запушить такой откат в main:

```bash
git push origin main --force
```

`--force` использовать только когда точно понимаешь, что хочешь переписать историю.

---

## 16. Git: если VS Code показывает “висячие” изменения

Проверить реально ли есть изменения:

```bash
git status
```

Если пишет “нечего коммитить”, но VS Code показывает метки:

```bash
git update-index -q --refresh
```

Потом перезапустить VS Code или выполнить Reload Window.

---

## 17. Ручной деплой dev с сервера

```bash
cd /var/www/axelio/dev/repo
git checkout develop
git pull origin develop

cd backend
source /var/www/axelio/dev/venv/bin/activate
pip install -r requirements.txt
alembic upgrade head

sudo systemctl restart axelio-api-dev
sudo systemctl restart axelio-bot-dev
sudo systemctl reload nginx
```

Проверка:

```bash
curl http://127.0.0.1:9001/health
journalctl -u axelio-api-dev -n 50 --no-pager
journalctl -u axelio-bot-dev -n 50 --no-pager
```

---

## 18. Быстрый чек после деплоя

```bash
sudo systemctl status axelio-api-dev --no-pager
sudo systemctl status axelio-bot-dev --no-pager
sudo nginx -t
curl http://127.0.0.1:9001/health
```

Если что-то упало:

```bash
journalctl -u axelio-api-dev -n 100 --no-pager
journalctl -u axelio-bot-dev -n 100 --no-pager
sudo tail -n 100 /var/log/nginx/error.log
```