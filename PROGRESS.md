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
**Дата последнего обновления:** 20.08.2026  
**Общий статус:** 📦 MVP + синхронизация статусов WB + Честный знак (приёмка + сборка)  
**Стадия:** Следующий шаг — поставки (§9)

**Выбранный стек:**
- Backend: Python 3.12 + Django 5 + Django REST Framework
- БД: PostgreSQL 16
- Очереди: Celery + Redis
- Frontend: React 19 + Vite + TypeScript + react-router-dom
- Auth: JWT + RBAC (admin / manager / seller)
- Деплой: Docker Compose **только на сервере** (на ПК Docker не нужен)
- Статика: WhiteNoise (админка Django)

**Версия синхронизации статусов:** `delivery-v6` (проверка: `GET /api/health/` → `"sync_version":"delivery-v6"`)

---

## Инфраструктура (важно!)

| Параметр | Значение |
|----------|----------|
| **GitHub** | https://github.com/egurchenkovwallstreet-sys/fulfillment-crm |
| **Папка на сервере** | `/opt/fulfillment-crm` |
| **IP сервера** | `5.129.243.246` (Timeweb VPS) |
| **Frontend (дашборд)** | http://5.129.243.246:8080 |
| **Backend + админка** | http://5.129.243.246:8080/admin/ или :8001/admin/ (**порт обязателен!**) |
| **API** | через nginx frontend: `/api/` → `web:8000` |

### Изоляция от других проектов (НЕ ТРОГАТЬ!)
| Проект | Путь на сервере | Порт |
|--------|-----------------|------|
| wb-chz | `/opt/wb-chz` | 8000 |
| darom_app | `/opt/darom_app` | 3000 (API), 80/443 nginx |
| **fulfillment CRM** | `/opt/fulfillment-crm` | **8001**, **8080** |

### Workflow заказчика
1. Редактирование кода в Cursor на ПК (`C:\Users\User\срм фул`)
2. `git push` на GitHub (ассистент)
3. На сервере:
   ```bash
   cd /opt/fulfillment-crm
   git fetch origin main && git reset --hard origin/main
   docker compose build --no-cache frontend web worker
   docker compose up -d frontend web worker
   ```
4. Python на ПК **не установлен** — это нормально

### Учётные данные
- Админ: `E.Gurchenkov@yandex.ru` / логин `admin@test.ru`
- Пароль задавался при `createsuperuser` на сервере

---

## Сверка с TZ.md (что сделано / частично / нет)

| Раздел ТЗ | Статус | Комментарий |
|-----------|--------|-------------|
| §2 Архитектура и стек | ✅ | Django + PostgreSQL + React, Docker на сервере |
| §3 Роли (admin / manager / seller) | 🟡 | JWT + RBAC, разграничение на API; кабинет селлера неполный |
| §4 Управление селлерами | 🟡 | Модель Seller, админка; нет генерации логина/пароля, токен вручную |
| §5 Модуль приёмки | ✅ | API + UI, авто-проверка needKiz (Content API), флаг requires_marking |
| §6 Заказы FBS, синхронизация | ✅ | Sync `/orders/new` с пагинацией, ручное + Celery 15 мин, статусы WB §6.3 |
| §6.3 Счётчики как в ЛК WB | ✅ | new / confirm / complete+waiting; кэш на Seller |
| §6 Лист подбора | ✅ | Группировка по ячейкам, UI, печать |
| §7 Сборка и печать этикеток FBS | 🟡 | ЧЗ перед печатью, bind sgtin, замена товара; Xprinter bridge — нет |
| §8 Честный знак (DataMatrix) | 🟡 | Приёмка (needKiz) + сборка (bind + print); блокировка поставок — в §9 |
| §9 Поставки и ШК | ❌ | Модель Supply, API/UI нет |
| §10 Списание остатков | ❌ | Не реализовано |
| §11 Возвраты | ❌ | Не реализовано |
| §12 Цены и финансы | 🟡 | Модели PriceGroup, individual_price; UI/API нет, менеджер не видит цены |
| §13 Дашборды и отчёты | 🟡 | KPI по стадиям WB (красный/оранжевый/синий); отчёты и финансы — нет |
| §14 Нефункциональные требования | 🟡 | Логи AuditLog, health endpoint; нагрузка, бэкапы, HTTPS — нет |
| §15 API Wildberries (полный набор) | 🟡 | Заказы new ✅; статусы ✅; стикеры ✅; остатки, ЧЗ, поставки — нет |

**Легенда:** ✅ готово · 🟡 частично · ❌ не начато

---

## Выполненные этапы

| Дата | Этап | Статус | Комментарий |
|------|------|--------|-------------|
| 16.08.2026 | Сбор требований, TZ.md, структура проекта | ✅ | |
| 16.08.2026 | Docker, деплой, GitHub, WhiteNoise, дашборд | ✅ | |
| 16.08.2026 | JWT авторизация + роли | ✅ | |
| 17.08.2026 | Модуль приёмки | ✅ | API + UI |
| 18.08.2026 | Починка деплоя (миграции, web, админка, CSRF) | ✅ | |
| 18.08.2026 | Модуль заказов FBS + лист подбора | ✅ | WB client, пагинация, UI /orders |
| 18.08.2026 | UI-фиксы заказов | ✅ | Статус колонки, счётчики sync |
| 18.08.2026 | Модуль сборки FBS (кабинет менеджера) | ✅ | API assembly, стикеры WB, UI /assembly |
| 19.08.2026 | Синхронизация статусов WB | ✅ | `wb_supplier_status`, `wb_status`, POST /orders/status |
| 19.08.2026 | Дашборд: карточки по стадиям WB | ✅ | Новые (красный), На сборке, В доставке |
| 19.08.2026 | Исправление счётчика «В доставке» | ✅ | `complete + waiting` (не sorted); сверка с ЛК WB (~108) |
| 19.08.2026 | Кэш счётчиков на Seller | ✅ | `wb_count_new/assembly/delivery`, reconcile при sync |
| 19.08.2026 | Инфра: nginx 502/404, deploy.sh | ✅ | no-cache index.html, скрипт деплоя |
| 20.08.2026 | Честный знак: приёмка needKiz + сборка bind/print | ✅ | Content API, sgtin, замена товара |

---

## Что реализовано по модулям

### Backend (Django apps)
- **accounts** — User (admin/manager/seller), JWT, `/api/auth/me/`
- **sellers** — Seller, WB-токен, кэш счётчиков `wb_count_*`
- **warehouse** — Cell, Product, PriceGroup, StockOperation, приёмка
- **orders** — Order (`wb_supplier_status`, `wb_status`), PickList; sync, статусы, лист подбора, сборка, стикеры, scan-print
  - `services/wb_status.py` — правила «В доставке» (`waiting`), фильтры исключений
  - `services/sync_statuses.py` — sync статусов, reconcile, `SYNC_VERSION = delivery-v6`
- **integrations** — AuditLog, `wb_client.py`, Celery `sync_wb_orders`

### API endpoints (работают)
| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/auth/login/` | Вход |
| GET | `/api/auth/me/` | Текущий пользователь |
| POST | `/api/auth/token/refresh/` | Обновление токена |
| GET | `/api/health/` | Health + `sync_version` |
| GET | `/api/warehouse/sellers/` | Список селлеров |
| GET | `/api/warehouse/cells/` | Ячейки |
| GET/POST | `/api/warehouse/intake/*` | Приёмка |
| GET | `/api/orders/` | Заказы FBS |
| GET | `/api/orders/stats/` | KPI дашборда (из кэша Seller) |
| POST | `/api/orders/sync/` | Синхронизация WB (заказы + статусы + reconcile) |
| GET/POST | `/api/orders/pick-lists/*` | Лист подбора |
| GET | `/api/orders/assembly/sellers/` | Селлеры со счётчиками стадий |
| GET | `/api/orders/assembly/sellers/<id>/` | Кабинет сборки селлера |
| POST | `/api/orders/assembly/sellers/<id>/start/` | Начать сборку (лист + стикеры) |
| POST | `/api/orders/assembly/sellers/<id>/scan-print/` | Скан → печать стикера |

### Frontend (React)
- `/login` — вход
- `/` — дашборд: **Новые заказы** (красный), **На сборке**, **В доставке**, «Обновить данные WB»
- `/intake` — приёмка (admin + manager)
- `/assembly` — сборка FBS: список селлеров, счётчики, sync WB
- `/assembly/:sellerId` — кабинет сборки: вкладки **Новые / На сборке / В доставке** (цвета как дашборд), «Начать сборку», лист подбора, печать по скану
- `/orders` — редирект на `/assembly`

### Management commands
- `seed_cells` — ячейки 1..50

### Скрипты
- `scripts/deploy.sh` — обновление с сервера (fetch, build, up)

---

## Логика «В доставке» (зафиксировано в TZ §6.3)

| Статус | Входит в «В доставке»? |
|--------|------------------------|
| `complete` + `waiting` | ✅ Да |
| `complete` + `sorted` | ❌ Нет |
| `sold`, отмены, `declined_by_client` | ❌ Нет (reconcile → shipped) |

Сверка с ЛК WB: при ~108 заказах во вкладке «В доставке» CRM показывает то же число после sync.

---

## Ближайшие задачи (очередь по ТЗ)

### Следующий спринт (приоритет 1)
1. [ ] **§9 Поставки** — формирование, блокировка без ЧЗ, ШК поставки (QR)
2. [ ] **§7 Xprinter** — print-bridge для прямой печати (< 2 сек), поддержка 365 и 370

### Спринт 2 (после поставок)
4. [ ] **§10 Списание остатков** — автоматически после подтверждения поставки WB
5. [ ] **§15 WB API — остатки** — реализовать `sync_wb_stocks` (сейчас заглушка)
6. [ ] **§4 Селлеры** — удобный ввод/шифрование токена WB, генерация логина/пароля селлера

### Спринт 3 (кабинеты и финансы)
7. [ ] **§11 Возвраты** — кнопка «Возврат», как приёмка
8. [ ] **§12 Финансы** — ценовые группы, отчёты (только admin)
9. [ ] **§13 Дашборды** — отчёты за день/неделю/месяц, кабинет селлера
10. [ ] **§3 Кабинет селлера** — остатки, заказы, «Обновить данные»

### Техдолг и продакшен
11. [ ] Тесты для `wb_status.py` и sync reconcile
12. [ ] Цветовые вкладки на `/assembly` (список селлеров) — по желанию
13. [ ] **§14 Нагрузка** — тест 10 000 заказов/день, индексы
14. [ ] **§14 Продакшен** — домен, HTTPS, бэкап БД, `WB_TOKEN_ENCRYPTION_KEY` в `.env`

### Уже сделано ✅
- [x] Стек, БД, Docker, деплой
- [x] JWT + роли
- [x] Приёмка
- [x] Админка (миграции, CSRF, :8080/admin)
- [x] Заказы FBS + лист подбора + пагинация WB
- [x] Сборка FBS: кабинет менеджера, стикеры WB, печать по скану
- [x] Синхронизация статусов WB + счётчики как в ЛК
- [x] Дашборд KPI (Новые / На сборке / В доставке)
- [x] Кэш счётчиков на Seller, health endpoint
- [x] Честный знак: авто needKiz при приёмке, bind ЧЗ на сборке, замена товара

---

## Текущие проблемы и риски

| Проблема | Статус | Что делать |
|----------|--------|------------|
| Админка без порта → 404 | ℹ️ | Только `:8080/admin` или `:8001/admin` |
| Заказы без ячейки (—) | ℹ️ | Сначала приёмка товара с тем же баркодом |
| WB_TOKEN_ENCRYPTION_KEY пустой | ⚠️ | Задать в `.env` на сервере для шифрования токенов |
| Печать Xprinter из браузера | ⚠️ | Нужен print-bridge (следующий спринт) |
| Старый UI после деплоя | ℹ️ | `git reset --hard origin/main`, `build --no-cache frontend` |
| `git pull` конфликт docker-compose | ⚠️ | `git checkout -- docker-compose.yml` или `reset --hard` |

---

## История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 16.08.2026 | TZ.md, инициализация, Docker | Ассистент |
| 16.08.2026 | JWT, дашборд, WhiteNoise | Ассистент |
| 17.08.2026 | Модуль приёмки | Ассистент |
| 18.08.2026 | Фикс деплоя, миграции, админка, CSRF | Ассистент |
| 18.08.2026 | Заказы FBS, лист подбора, пагинация WB | Ассистент |
| 18.08.2026 | Сверка с TZ, обновление PROGRESS | Ассистент |
| 18.08.2026 | Модуль сборки FBS (кабинет менеджера) | Ассистент |
| 19–20.08.2026 | Статусы WB, счётчики дашборда, delivery-v6, UI сборки | Ассистент |
| 20.08.2026 | Обновление TZ §6.3, §7, §13, §15 и PROGRESS | Ассистент |

---

## Git-коммиты (основные)
- `7e542d4` — Intake module
- `7fe7ca5` — Orders FBS + pick list
- `92c0a10` — WB pagination fix
- `ab6a103` — Assembly module (stickers, start_assembly, scan-print)
- `0ce1962` — Sync fallback fix (recent_ids)
- `b7d12d0` — Delivery count: complete + waiting only
- `7976b98` — Remove dashboard sync debug line
- `aba7743` — Assembly UI: colored stage tabs, remove «Все активные»

---

**Конец файла PROGRESS.md**
