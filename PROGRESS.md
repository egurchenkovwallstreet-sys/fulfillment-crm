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
**Дата последнего обновления:** 22.08.2026  
**Общий статус:** 📦 MVP + **полная синхронизация счётчиков с ЛК WB** + Честный знак + поштучные поставки + **§5 приёмка закрыта**  
**Стадия:** Следующий шаг — полный модуль поставок (§9 UI), Xprinter, списание остатков (§10)

**Выбранный стек:**
- Backend: Python 3.12 + Django 5 + Django REST Framework
- БД: PostgreSQL 16
- Очереди: Celery + Redis
- Frontend: React 19 + Vite + TypeScript + react-router-dom
- Auth: JWT + RBAC (admin / manager / seller)
- Деплой: Docker Compose **только на сервере** (на ПК Docker не нужен)
- Статика: WhiteNoise (админка Django)

**Версия синхронизации статусов:** `delivery-v10` (проверка: `GET /api/health/` → `"sync_version":"delivery-v10"`)

### ✅ Сверка с ЛК Wildberries (21.08.2026, ИП Мазирка)
| Вкладка | ЛК WB | CRM | Статус |
|---------|-------|-----|--------|
| Новые | 31 | 31 | ✅ |
| На сборке | 0 | 0 | ✅ |
| В доставке | 147 | 147 | ✅ |

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
   git pull && bash scripts/deploy.sh
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
| §4 Управление селлерами | 🟡 | Модель Seller, админка; склады WB (SellerWarehouse), фильтр; токен вручную |
| §5 Модуль приёмки | ✅ | API + UI, needKiz, этикетки ячеек 75×120, раздел «Ячейки», перенос, **обновление названий из WB** (кнопка + Celery 03:00) |
| §6 Заказы FBS, синхронизация | ✅ | Sync new + архив 30 дн. + статусы, Celery 15 мин |
| §6.3 Счётчики как в ЛК WB | ✅ | **31/0/147 совпадает**; live API + кэш Seller; delivery-v10 |
| §6 Лист подбора | ✅ | Группировка по ячейкам, UI, печать |
| §7 Сборка и печать этикеток FBS | 🟡 | ЧЗ, bind sgtin, **поштучная сборка/доставка**; Xprinter bridge — нет |
| §8 Честный знак (DataMatrix) | 🟡 | Приёмка (needKiz) + сборка (bind + print); блокировка поставок — в §9 |
| §9 Поставки и ШК | 🟡 | Модель Supply, supply_flow (create/add/deliver/barcode); UI раздела — нет |
| §10 Списание остатков | ❌ | Не реализовано |
| §11 Возвраты | ❌ | Не реализовано |
| §12 Цены и финансы | 🟡 | Модели PriceGroup, individual_price; UI/API нет |
| §13 Дашборды и отчёты | 🟡 | KPI по стадиям WB **синхронизированы**; отчёты и финансы — нет |
| §14 Нефункциональные требования | 🟡 | Логи AuditLog, health endpoint; HTTPS, бэкапы — нет |
| §15 API Wildberries (полный набор) | 🟡 | Заказы, статусы, стикеры, ЧЗ, поставки ✅; остатки — нет |

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
| 19.08.2026 | Исправление счётчика «В доставке» | ✅ | `complete + waiting` (не sorted) |
| 19.08.2026 | Кэш счётчиков на Seller | ✅ | `wb_count_new/assembly/delivery`, reconcile при sync |
| 19.08.2026 | Инфра: nginx 502/404, deploy.sh | ✅ | no-cache index.html, скрипт деплоя |
| 20.08.2026 | Честный знак: приёмка needKiz + сборка bind/print | ✅ | Content API, sgtin, замена товара |
| 21.08.2026 | Поштучная сборка/доставка через WB supplies | ✅ | «На сборку», «Все на сборку», «В доставку» |
| 21.08.2026 | Фильтр складов WB (SellerWarehouse) | ✅ | Включение/выключение точек отгрузки в UI сборки |
| 21.08.2026 | Синхронизация счётчиков delivery-v7…v10 | ✅ | Исправлены расхождения 139/147/490; **полное совпадение с ЛК** |
| 21.08.2026 | Деплой: migrate только в web, frontend build fix | ✅ | IntegrityError, stageCount TS fix |
| 22.08.2026 | §5.3 Этикетки ячеек + раздел «Ячейки» | ✅ | Печать 75×120 мм, перенос, CellLabelPrompt |
| 22.08.2026 | §5 Обновление данных товаров из WB | ✅ | Кнопка «Обновить из WB», daily sync 03:00, точный поиск по SKU |
| 22.08.2026 | **§5 Модуль приёмки — этап закрыт** | ✅ | Подтверждено заказчиком |
| 22.08.2026 | §6.2 Печать листа подбора (PDF A4) | ✅ | Макет утверждён, кнопка в сборке |

---

## Что реализовано по модулям

### Backend (Django apps)
- **accounts** — User (admin/manager/seller), JWT, `/api/auth/me/`
- **sellers** — Seller, SellerWarehouse (склады WB, is_enabled), WB-токен, кэш счётчиков `wb_count_*`
- **warehouse** — Cell, Product, PriceGroup, StockOperation, приёмка, этикетки ячеек, перенос, sync названий из WB
- **orders** — Order, Supply, PickList; sync, статусы, лист подбора, сборка, supply_flow
  - `services/wb_status.py` — «В доставке» = `complete + waiting`; «Ждёт сортировки» в ЛК
  - `services/sync_statuses.py` — sync, reconcile, poll архив + поставки, `SYNC_VERSION = delivery-v10`
  - `services/supply_flow.py` — поштучная отправка на сборку/в доставку
  - `services/assembly.py` — `get_seller_wb_tab_counts()` (кэш live API)
- **integrations** — AuditLog, `wb_client.py` (orders, statuses, supplies, stickers), Celery

### API endpoints (работают)
| Метод | URL | Описание |
|-------|-----|----------|
| POST | `/api/auth/login/` | Вход |
| GET | `/api/auth/me/` | Текущий пользователь |
| GET | `/api/health/` | Health + `sync_version` |
| GET | `/api/orders/stats/` | KPI дашборда (кэш WB live API) |
| POST | `/api/orders/sync/` | Синхронизация WB (заказы + статусы + reconcile) |
| GET | `/api/orders/assembly/sellers/` | Селлеры со счётчиками стадий |
| GET | `/api/orders/assembly/sellers/<id>/` | Кабинет сборки (вкладки, склады, заказы) |
| POST | `/api/orders/assembly/sellers/<id>/send-to-assembly/` | Один заказ → сборка WB |
| POST | `/api/orders/assembly/sellers/<id>/send-all-to-assembly/` | Массовая отправка на сборку |
| POST | `/api/orders/assembly/sellers/<id>/send-to-delivery/` | Один заказ → доставка WB |
| POST | `/api/orders/assembly/sellers/<id>/start/` | Лист подбора + стикеры |
| POST | `/api/orders/assembly/sellers/<id>/scan-print/` | Скан → печать / ЧЗ |
| GET/POST | `/api/warehouse/intake/*` | Приёмка |
| GET | `/api/warehouse/sellers/<id>/products/` | Товары селлера по ячейкам |
| POST | `/api/warehouse/sellers/<id>/products/refresh-from-wb/` | Обновить названия/маркировку из WB |
| POST | `/api/warehouse/products/<id>/move-cell/` | Перенос товара в другую ячейку |
| GET | `/api/warehouse/products/<id>/cell-label/` | Данные для этикетки ячейки |
| GET/POST | `/api/orders/pick-lists/*` | Лист подбора |

### Frontend (React)
- `/` — дашборд: **Новые / На сборке / В доставке** — совпадает с ЛК WB
- `/assembly/:sellerId` — вкладки стадий, склады WB, «На сборку», «Все на сборку», «В доставку»
- `/intake` — приёмка
- `/cells` — ячейки: список товаров, печать этикеток, перенос, «Обновить из WB»
- `/login` — вход

---

## Логика «В доставке» (зафиксировано в TZ §6.3)

| Статус | Входит в «В доставке»? |
|--------|------------------------|
| `complete` + `waiting` | ✅ Да («Ждёт сортировки» в поставке WB) |
| `complete` + `sorted` | ❌ Нет (уже на СЦ WB) |
| `sold`, отмены, `ready_for_pickup`, `defect` | ❌ Нет (reconcile → shipped/cancelled) |

**Источник счётчика:** live API при sync (не полная история БД). Опрос ID: БД + архив 30 дн. + заказы из поставок `done=true`.

**Проверено 21.08.2026:** CRM = ЛК WB (147 в доставке, 31 новых, 0 на сборке).

---

## Ближайшие задачи (очередь по ТЗ)

### Следующий спринт (приоритет 1)
1. [ ] **§9 Поставки (UI)** — раздел «Поставки», массовые поставки, блокировка без ЧЗ
2. [ ] **§7 Xprinter** — print-bridge для прямой печати (< 2 сек)

### Спринт 2
3. [ ] **§10 Списание остатков** — после подтверждения поставки WB
4. [ ] **§15 WB API — остатки** — `sync_wb_stocks`
5. [ ] **§4 Селлеры** — генерация логина/пароля, UI токена WB

### Спринт 3
6. [ ] **§11 Возвраты**
7. [ ] **§12–13 Финансы и отчёты**
8. [ ] **§3 Кабинет селлера**

### Техдолг
9. [ ] Тесты для `wb_status.py` и sync reconcile
10. [ ] **§14 Продакшен** — HTTPS, бэкап БД, `WB_TOKEN_ENCRYPTION_KEY`

### Уже сделано ✅
- [x] Стек, БД, Docker, деплой
- [x] **§5 Модуль приёмки** (приёмка, ячейки, этикетки, перенос, sync названий WB)
- [x] Сборка FBS: кабинет, стикеры, ЧЗ, scan-print
- [x] **Счётчики WB = ЛК WB (delivery-v10)**
- [x] Поштучная отправка на сборку и в доставку (WB supplies API)
- [x] Фильтр складов SellerWarehouse
- [x] Массовая «Все на сборку»
- [x] Архив заказов + опрос поставок в доставке для точного счётчика

---

## Текущие проблемы и риски

| Проблема | Статус | Что делать |
|----------|--------|------------|
| Расхождение счётчиков CRM vs WB | ✅ **Решено** | delivery-v10, проверено 21.08.2026 |
| Админка без порта → 404 | ℹ️ | Только `:8080/admin` или `:8001/admin` |
| Заказы без ячейки (—) | ℹ️ | Сначала приёмка товара с тем же баркодом |
| WB_TOKEN_ENCRYPTION_KEY пустой | ⚠️ | Задать в `.env` на сервере |
| Печать Xprinter из браузера | ⚠️ | Нужен print-bridge (следующий спринт) |
| Старый UI после деплоя | ℹ️ | `git pull && bash scripts/deploy.sh` |

---

## История изменений

| Дата | Изменение | Автор |
|------|-----------|-------|
| 16.08.2026 | TZ.md, инициализация, Docker | Ассистент |
| 16–18.08.2026 | JWT, приёмка, заказы, сборка | Ассистент |
| 19–20.08.2026 | Статусы WB, счётчики, ЧЗ | Ассистент |
| **21.08.2026** | **Полная синхронизация с ЛК WB, supply_flow, delivery-v10** | Ассистент |
| **22.08.2026** | **§5 приёмка закрыта: ячейки, этикетки, sync WB** | Заказчик + Ассистент |

---

## Git-коммиты (основные, август 2026)
- `4c4cf1c` — Per-order send to assembly/delivery via WB supplies
- `c1fb424` — Warehouse filter, bulk «Все на сборку»
- `d9bbef2` — Unify counters, archive backfill, delivery-v7
- `92a3271` — delivery-v8 (sorted — откат)
- `d47cde5` — delivery-v9: waiting only, live API cache
- `0e8a6dc` — delivery-v10: poll archive + supply orders
- `93845ef` — Fix frontend build (stageCount conflict)
- `45fbae5` — WB product refresh + fix barcode lookup
- `6c8e96c` — Cell label printing, /cells page
- `8f0d7de` — Label 75×120 mm

---

**Конец файла PROGRESS.md**
