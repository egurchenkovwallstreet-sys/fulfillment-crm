# Файл 2: PROGRESS.md — Файл прогресса разработки

## Инструкция для Codex (ИИ-ассистента)
**Этот файл — журнал состояния разработки.**
- Ты ОБЯЗАН обновлять его после каждого значимого этапа.
- При каждом новом окне/обсуждении ты читаешь этот файл, чтобы понять, что сделано, что в работе, что отложено.
- Никогда не начинай новую задачу, не обновив прогресс по предыдущей.
- Структура строгая: дата, статус, что сделано, что в работе, проблемы.

**Также читай:** `TZ.md` (единственный источник истины по требованиям), `docs/NEW_CHAT_PROMPT.md` (контекст для нового чата).

---

## Текущий статус проекта
**Дата последнего обновления:** 18.08.2026  
**Общий статус:** 🔧 Исправление падения backend (контейнер web)  
**Стадия:** Деплой фикса миграций + перезапуск на сервере

**Выбранный стек:**
- Backend: Python 3.12 + Django 5 + Django REST Framework
- БД: PostgreSQL 16
- Очереди: Celery + Redis
- Frontend: React 19 + Vite + TypeScript + react-router-dom
- Auth: JWT + RBAC (admin / manager / seller)
- Деплой: Docker Compose **только на сервере** (на ПК Docker не нужен)
- Статика: WhiteNoise (админка Django)

---

## Инфраструктура (важно!)

| Параметр | Значение |
|----------|----------|
| **GitHub** | https://github.com/egurchenkovwallstreet-sys/fulfillment-crm |
| **Папка на сервере** | `/opt/fulfillment-crm` |
| **IP сервера** | `5.129.243.246` (Timeweb VPS) |
| **Frontend (дашборд)** | http://5.129.243.246:8080 |
| **Backend + админка** | http://5.129.243.246:8001/admin |
| **API** | http://5.129.243.246:8001/api/ (через nginx frontend: `/api/` → `web:8000`) |

### Изоляция от других проектов (НЕ ТРОГАТЬ!)
| Проект | Путь на сервере | Порт |
|--------|-----------------|------|
| wb-chz | `/opt/wb-chz` | 8000 |
| darom_app | `/opt/darom_app` | 3000 (API), 80/443 nginx |
| **fulfillment CRM** | `/opt/fulfillment-crm` | **8001**, **8080** |

### Workflow заказчика
1. Редактирование кода в Cursor на ПК (`C:\Users\User\срм фул`)
2. `git push` на GitHub
3. На сервере (консоль Timeweb): `cd /opt/fulfillment-crm && git pull && docker compose up --build -d`
4. Python на ПК **не установлен** — это нормально

### Учётные данные
- Админ назначен на почту: `E.Gurchenkov@yandex.ru`
- Логин мог быть `admin@test.ru` (уточнить у заказчика)
- Пароль задавался при `createsuperuser` на сервере

---

## Выполненные этапы

| Дата | Этап | Статус | Комментарий |
|------|------|--------|-------------|
| 16.08.2026 | Сбор требований от заказчика | ✅ | Все процессы описаны, роли определены |
| 16.08.2026 | Составление TZ.md | ✅ | Полное ТЗ, версия 1.0 |
| 16.08.2026 | Создание PROGRESS.md | ✅ | Файл прогресса |
| 16.08.2026 | Выбор стека | ✅ | Django + PostgreSQL + React |
| 16.08.2026 | Инициализация проекта | ✅ | backend/, frontend/, docs/ |
| 16.08.2026 | Модели БД (черновик) | ✅ | accounts, sellers, warehouse, orders, integrations |
| 16.08.2026 | Docker Compose | ✅ | web, worker, beat, db, redis, frontend |
| 16.08.2026 | Деплой на сервер | ✅ | `/opt/fulfillment-crm`, порты 8001/8080 |
| 16.08.2026 | GitHub репозиторий | ✅ | fulfillment-crm |
| 16.08.2026 | Исправление стилей админки | ✅ | WhiteNoise |
| 16.08.2026 | Редизайн дашборда | ✅ | KPI, процесс FBS, роли |
| 16.08.2026 | Авторизация JWT + роли | ✅ | login, /me, страница входа, RBAC |
| 17.08.2026 | Назначение админа | ✅ | E.Gurchenkov@yandex.ru |
| 17.08.2026 | Модуль приёмки | ✅ | API + UI, ячейки, история |

---

## Что реализовано по модулям

### Backend (Django apps)
- **accounts** — User с ролями (admin/manager/seller), JWT login, `/api/auth/me/`
- **sellers** — модель Seller, WB-токен (зашифрованный, пока пустой)
- **warehouse** — Cell, Product, PriceGroup, StockOperation; **приёмка** (`services/intake.py`, views)
- **orders** — Order, PickList, Supply (модели, без API)
- **integrations** — AuditLog, Celery tasks (WB sync — заглушка)

### API endpoints (работают)
| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/auth/login/` | Вход, JWT + данные user |
| GET | `/api/auth/me/` | Текущий пользователь |
| POST | `/api/auth/token/refresh/` | Обновление токена |
| GET | `/api/warehouse/sellers/` | Список селлеров |
| GET | `/api/warehouse/cells/?free=1` | Ячейки |
| GET | `/api/warehouse/intake/lookup/` | Поиск баркода |
| POST | `/api/warehouse/intake/` | Приёмка товара |
| GET | `/api/warehouse/intake/history/` | История приёмок |

### Frontend (React)
- Страница входа `/login`
- Дашборд `/` (по ролям)
- Приёмка `/intake` (admin + manager)
- Боковое меню, защищённые маршруты
- API через nginx proxy `/api/` → backend

### Management commands
- `python manage.py seed_cells` — создаёт ячейки 1..50 (если пусто)

---

## Ближайшие задачи (очередь)

1. [x] Выбор стека технологий
2. [x] Проектирование базы данных
3. [x] Авторизация и роли (JWT, RBAC)
4. [x] Модуль приёмки
5. [x] **Починить админку** — миграции в git, entrypoint без makemigrations
6. [ ] Модуль заказов и листа подбора
7. [ ] Интеграция с API Wildberries FBS (тестовый контур)
8. [ ] Модуль печати этикеток FBS (Xprinter 365/370)
9. [ ] Модуль Честного знака
10. [ ] Модуль поставок и ШК
11. [ ] Модуль возвратов
12. [ ] Личные кабинеты (полноценные)
13. [ ] Дашборды и отчёты (реальные данные)
14. [ ] Тестирование нагрузки (10 000 заказов/день)
15. [ ] Документация и продакшен-домен (nginx + HTTPS)

---

## Текущие проблемы и риски

| Проблема | Статус | Что делать |
|----------|--------|------------|
| Админка :8001 не открывается (контейнер web unhealthy) | 🔧 В работе | Фикс: `--fake-initial`, healthcheck по порту, ALLOWED_HOSTS всегда включает localhost/web |
| `git pull` конфликт docker-compose.yml | ⚠️ Было | На сервере: `git checkout -- docker-compose.yml` перед pull, или не править файл вручную |
| Python на ПК не установлен | ✅ Решено | Docker только на сервере |
| Xprinter из веб | ⚠️ Исследование | Локальный print-bridge |
| Честный знак API WB | ⚠️ Тестирование | Тестовые КИЗ |
| WB sync остатков | ⚠️ Заглушка | `sync_wb_stocks` — только лог, API не подключён |
| Нет селлеров в БД для теста приёмки | ℹ️ | Добавить в /admin → Селлеры |

### Диагностика админки (для ассистента)
```bash
cd /opt/fulfillment-crm
docker compose ps
docker compose logs web --tail 80
curl -I http://127.0.0.1:8001/admin/
docker compose up --build -d
```

---

## История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 16.08.2026 | Создан PROGRESS.md | Заказчик |
| 16.08.2026 | TZ.md, инициализация проекта | Ассистент |
| 16.08.2026 | Docker-стек, деплой docs | Ассистент |
| 16.08.2026 | WhiteNoise, редизайн UI, frontend Docker :8080 | Ассистент |
| 16.08.2026 | JWT авторизация, login page | Ассистент |
| 17.08.2026 | Модуль приёмки (API + IntakePage) | Ассистент |
| 18.08.2026 | Фикс: Django migrations в git, entrypoint, healthcheck web | Ассистент |

---

## Git-коммиты (основные)
- `8a7a5cb` — Initial commit
- `e40585d` — Fix admin styles, dashboard UI
- `a87a128` — JWT authentication
- `7e542d4` — Intake module

---

**Конец файла PROGRESS.md**
