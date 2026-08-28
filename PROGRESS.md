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
**Дата последнего обновления:** 29.08.2026  
**Общий статус:** 📦 Операционный MVP + Ozon FBS + **кабинет владельца** (`/owner`)  
**Стадия:** **Ozon FBS шаг 5 закрыт** (кабинет селлера и `/billing` по Ozon). Дальше: полировка и тесты (шаг 6). План: `тз и прогрес/2026-08-27-ozon-fbs-план.md`.

**Выбранный стек:**
- Backend: Python 3.12 + Django 5 + Django REST Framework
- БД: PostgreSQL 16
- Очереди: Celery + Redis
- Frontend: React 19 + Vite + TypeScript + react-router-dom
- Auth: JWT + RBAC (admin / manager / seller)
- Деплой: Docker Compose **только на сервере** (на ПК Docker не нужен)
- Статика: WhiteNoise (админка Django)

**Версия синхронизации статусов:** `delivery-v11` (проверка: `GET /api/health/` → `"sync_version":"delivery-v11"`)

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
| §2 Архитектура и стек | 🟡 | Multi-tenant: модель **Fulfillment**, изоляция данных ✅; регистрация `/signup` ✅ |
| §3 Роли (admin / manager / seller) | 🟡 | JWT + RBAC; кабинет селлера ✅; задолженность селлеру — нет |
| §4 Управление селлерами | 🟡 | Seller, склады WB, инвайты; **тарифы в UI** ✅; **токен WB в кабинете владельца** ✅ |
| §5 Модуль приёмки | ✅ | API + UI, needKiz, этикетки, перенос, sync названий; **хаб `/warehouse`**: каталог WB и Ozon, онбординг ячеек, перенос остатков между складами FBS |
| §5.4 Приёмка в XL | ✅ | `/intake-xl`: автосохранение скана, контрольная точка «Сохранить», Excel, ячейки после WB, **возобновление скана после applied**, **«Завершить приёмку»** (`6af6be3`) |
| §6 Заказы FBS, синхронизация | ✅ | Sync new + архив 30 дн. + статусы, Celery 15 мин |
| §6.3 Счётчики как в ЛК WB | ✅ | **31/0/147 совпадает**; live API + кэш Seller; delivery-v11 |
| §6 Лист подбора | ✅ | Группировка по ячейкам, UI, печать |
| §7 Сборка и печать этикеток FBS | ✅ | ЧЗ, панели очереди, быстрый баркод→ЧЗ; печать Chrome/агент |
| §8 Честный знак (DataMatrix) | ✅ | Фоновая проверка 3+3 сек; панели «Ошибки»/«Без ЧЗ»; блок доставки |
| §9 Поставки и ШК | ✅ | Весь цикл в «Сборке FBS»: лист → скан → ЧЗ → QR поставки, блокировка шагов |
| §10 Списание остатков | ✅ | Авто при «В доставку» + при sync поставок `done=true` |
| §11 Возвраты | ❌ | **Не делаем** — возврат как новая партия (приёмка / XL) |
| §12 Цены и финансы | 🟡 | **Тарифы** ✅, **отгрузки × тариф** ✅, **админ `/billing`** ✅; отчёты д/м/всё время — нет |
| §13 Дашборды и отчёты | 🟡 | KPI WB ✅; кабинет селлера ✅; **кабинет владельца** ✅; задолженность и отчёты д/м — нет |
| §14 Нефункциональные требования | 🟡 | Логи AuditLog, health endpoint; HTTPS, бэкапы — нет |
| §15 API Wildberries (полный набор) | 🟡 | Заказы, статусы, стикеры, ЧЗ, поставки, Statistics ✅; остатки FBS при приёмке/онбординге ✅ |

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
| 22.08.2026 | **Сборка FBS: синхронизация вкладки «Новые»** | ✅ | delivery-v11: reconcile stale new, sync при входе, Celery 1 мин |
| 24.08.2026 | **Сборка FBS: единый счётчик «Новые»** | ✅ | `new_stage_orders_queryset`, удалён `shipped_missing`, сброс stale CRM status |
| 24.08.2026 | **Кабинет селлера: календарная статистика** | ✅ | День/неделя/месяц МСК, стадии WB, сравнение с прошлым периодом |
| 24.08.2026 | **Кабинет селлера: WB Statistics API** | ✅ | `supplier/orders`, уникальные `srid`, FBS; как сводный отчёт WB |
| 24.08.2026 | **Кабинет селлера: отгрузки 4 недели** | ✅ | Интерактивный график, вкладки недель, `done` supplies |
| 24.08.2026 | **Fix кабинета 500 / нулевые счётчики** | ✅ | Statistics API, `_order_identity`, фильтр FBS |
| 24.08.2026 | **Тарифы селлера (админ UI)** | ✅ | `/sellers` → Тариф; все товары / ценовая группа |
| 24.08.2026 | **Суммы ₽ в отгрузках кабинета** | ✅ | заказы × тариф по дням и неделе |
| 24.08.2026 | **Отгрузки: все заказы WB** | ✅ | не только CRM; order-ids из WB API |
| 24.08.2026 | **Админ `/billing`** | ✅ | все селлеры + итого, 4 недели, таблица |
| 24.08.2026 | **§9 + §10 в сборке FBS** | ✅ | QR поставки, блокировка шагов, автосписание |
| 24.08.2026 | **Аудит реализации vs ТЗ** | ✅ | Журнал приведён к коду; очередь — §11 |
| 25.08.2026 | **Сборка FBS: лист подбора, удаление заказа, PDF** | ✅ | `bf1c0a9`, `b193547`; `assembly_hidden`, preview pick list |
| 25.08.2026 | **Одна поставка WB на склад + артикул/размер в листе** | ✅ | `a243096`, `Supply.wb_warehouse_id` |
| 25.08.2026 | **Агент печати: install-agent.bat** | ✅ | `0b67b58`, `/print-agent` |
| 25.08.2026 | **Списание остатков при доставке через ЛК WB** | ✅ | `5555e25`, `supply_sync.py`, `deduct_pending_delivery_stock` |
| 27.08.2026 | **Приёмка в XL** | ✅ | Новый клиент без API: скан единиц, Excel, ячейки после токена WB |
| 28.08.2026 | **Multi-tenant Fulfillment** | ✅ | Изоляция селлеров/менеджеров/тарифов; регистрация `/signup` |
| 29.08.2026 | **Приёмка в XL: возобновление скана** | ✅ | Скан после save/applied, дельта WB, статус `completed`, миграция `0007` (`6af6be3`) |

---

## Что реализовано по модулям

### Backend (Django apps)
- **accounts** — User (admin/manager/seller), JWT, `/api/auth/me/`
- **sellers** — Seller, SellerWarehouse, WB-токен, кэш счётчиков `wb_count_*`
  - `services/wb_order_stats.py` — Statistics API, заказы д/н/м
  - `services/seller_billing_stats.py` — отгрузки WB (4 нед.), суммы, merge для админа
  - `services/seller_analytics.py` — payload кабинета селлера
  - `services/calendar_periods.py` — календарь МСК
- **warehouse** — Cell, Product, PriceGroup, приёмка, этикетки, перенос, sync WB
  - `services/seller_pricing.py` — назначение тарифов селлеру
  - `views_pricing.py` — API price-groups и pricing
  - `services/onboarding.py` / `catalog_fetch.py` — мастер склада: каталог WB → ячейки
  - `services/wb_stocks.py` / `stock_transfer.py` — остатки FBS и перенос между складами
  - `services/stock_deduction.py` — списание при отгрузке
  - `services/xl_intake.py` — приёмка в XL (скан с автосохранением, Excel, ячейки после API, дельта WB, complete)
- **integrations** — AuditLog, `wb_client.py`, **`wb_statistics_client.py`**, Celery
- **orders** — Order, Supply, PickList; sync, статусы, лист подбора, сборка, supply_flow
  - `services/wb_status.py` — «В доставке» = `complete + waiting`; «Ждёт сортировки» в ЛК
  - `services/sync_statuses.py` — sync, reconcile, poll архив + поставки, `SYNC_VERSION = delivery-v14`
  - `services/supply_sync.py` — импорт поставок WB (в т.ч. из ЛК), scanDt, списание
  - `services/supply_flow.py` — одна поставка/склад, `delivery_stage_orders_queryset`
  - `services/assembly.py` — `get_seller_wb_tab_counts()` (кэш live API)

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
| GET | `/api/orders/assembly/sellers/<id>/marking-status/` | Панели «Ошибки ЧЗ» / «Без ЧЗ» |
| POST | `/api/orders/assembly/sellers/<id>/verify-marking/` | Фоновый опрос статуса ЧЗ в WB |
| POST | `/api/orders/assembly/sellers/<id>/ozon-scan/` | Скан баркода Ozon → «На сборке» |
| POST | `/api/orders/assembly/sellers/<id>/ozon-bind-marking/` | Привязка Честного знака Ozon |
| POST | `/api/orders/assembly/sellers/<id>/ozon-ship/` | `/v4/posting/fbs/ship` + списание CRM |
| POST | `/api/orders/assembly/sellers/<id>/ozon-label/` | PDF-этикетка (до 20 отправлений) |
| POST | `/api/orders/assembly/sellers/<id>/ozon-act/` | Акт/ШК сдачи (`carriage` create+approve) |
| POST | `/api/orders/assembly/sellers/<id>/ozon-sync/` | Синк отправлений Ozon |
| GET/POST | `/api/warehouse/inventory/*` | Инвентаризация склада |
| GET/POST | `/api/warehouse/xl-intake/sessions/` | Список / новая XL-приёмка (ИП без токена) |
| POST | `/api/warehouse/xl-intake/sessions/<id>/scan/` | Скан одной единицы (если не `completed`) |
| POST | `/api/warehouse/xl-intake/sessions/<id>/save/` | Контрольная точка (не блокирует скан) |
| GET | `/api/warehouse/xl-intake/sessions/<id>/excel/` | Скачать Excel (баркод, количество) |
| POST | `/api/warehouse/xl-intake/sessions/<id>/connect-wb/` | Токен WB → карточки, ячейки; повтор — только дельта |
| POST | `/api/warehouse/xl-intake/sessions/<id>/complete/` | Завершить приёмку (`completed`) |
| GET/POST | `/api/warehouse/onboarding/<id>/*` | Мастер склада: превью каталога WB, подтверждение |
| GET | `/api/warehouse/sellers/<id>/stock-overview/` | Остатки по складам FBS |
| POST | `/api/warehouse/sellers/<id>/stock-transfer/` | Перенос остатка между складами WB |
| POST | `/api/warehouse/sellers/<id>/ozon-stocks/` | Остатки CRM → выбранный склад Ozon FBS |
| GET | `/api/warehouse/sellers/<id>/products/` | Товары селлера по ячейкам |
| POST | `/api/warehouse/sellers/<id>/products/refresh-from-wb/` | Обновить названия/маркировку из WB |
| POST | `/api/warehouse/products/<id>/move-cell/` | Перенос товара в другую ячейку |
| GET | `/api/warehouse/products/<id>/cell-label/` | Данные для этикетки ячейки |
| GET/POST | `/api/orders/pick-lists/*` | Лист подбора |
| GET | `/api/sellers/cabinet/` | Кабинет селлера (статистика, стадии, отгрузки, товары) |
| GET | `/api/sellers/cabinet/barcode/<barcode>/` | Детализация по штрихкоду |
| GET | `/api/sellers/admin/billing/` | Админ: отгрузки всех селлеров + итого |
| GET/POST | `/api/auth/staff/` | Менеджеры: список / создание |
| PATCH | `/api/auth/staff/<id>/` | Менеджер: вкл/выкл, смена пароля |
| PATCH | `/api/sellers/manage/<id>/` | Селлер: название, is_active |
| POST/DELETE | `/api/sellers/manage/<id>/wb-token/` | Токен WB селлера |
| GET/POST | `/api/warehouse/price-groups/` | Ценовые группы (admin) |
| PATCH/DELETE | `/api/warehouse/price-groups/<id>/` | Редактирование группы |
| GET/POST | `/api/warehouse/sellers/<id>/pricing/` | Тарифы селлера (admin) |

### Frontend (React)
- `/` — дашборд: **Новые / На сборке / В доставке** — совпадает с ЛК WB
- `/assembly/:sellerId` — вкладки стадий; **Ozon:** скан, ЧЗ, ship, PDF-этикетка, акт/ШК
- `/inventory` — **инвентаризация:** скан баркодов, сверка CRM/WB, печать этикетки ячейки
- `/owner` — **кабинет владельца:** обзор, селлеры, сотрудники, ценовые группы, статистика
- `/owner/sellers` — селлеры, инвайты, токены WB/Ozon, тарифы
- `/owner/staff` — менеджеры склада
- `/owner/pricing` — ценовые группы
- `/owner/billing` — статистика отгрузок
- `/cabinet` — **кабинет селлера:** заказы д/н/м, стадии FBS, отгрузки 4 нед. + ₽ (WB или Ozon)
- `/warehouse` — **хаб склада:** онбординг каталога WB/Ozon, остатки на Ozon, перенос между складами WB
- `/intake` — приёмка
- `/intake-xl` — **приёмка в XL** (скан с автосохранением, Excel, WB, завершение; см. `тз и прогрес/2026-08-27-приемка-xl.md`)
- `/cells` — ячейки: список товаров, печать этикеток, перенос, «Обновить из WB»
- `/print-agent` — скачивание и инструкция агента Xprinter
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

### Приоритет 1 — операционка (осталось)
1. [x] **Ozon FBS шаг 1–4 + Celery + остатки** — вкладки, ключи, склады, онбординг, синк, скан/ЧЗ/ship, PDF-этикетка, акт/ШК, автосинк 1 мин, кнопка остатков на Ozon. План: `тз и прогрес/2026-08-27-ozon-fbs-план.md`.
2. [ ] **Ozon FBS шаг 6** — тесты, полировка UI
3. [x] **§4 UI токена WB** — в кабинете владельца → Селлеры → «Токен WB»
3. [ ] Отдельная кнопка **отправки остатков XL на склад WB** (после полноценного клиента)

### Приоритет 2 — финансы и отчёты
3. [ ] **§12.4** — отчёты выручки за день / месяц / всё время (не только 4 недели отгрузок)
4. [ ] **§13.3** — задолженность селлера в кабинете (сумма к оплате за обработку)
5. [ ] **§13.2** — детальный дашборд одного селлера для админа (не только сводная `/billing`)
6. [x] UI ценовых групп в CRM — `/owner/pricing`
7. [ ] Тариф по баркоду в UI (редактирование одного SKU без массового apply)

### Приоритет 3 — инфра
8. [ ] Кэширование админ `/billing` (сейчас 1–2 мин на загрузку — много запросов WB)
9. [ ] **§14 Продакшен** — HTTPS, бэкап БД, `WB_TOKEN_ENCRYPTION_KEY`

### Техдолг
14. [ ] Тесты: `wb_status.py`, sync reconcile, `seller_billing_stats`
15. [ ] Statistics API: кэш на 30 мин (лимит 1 req/min)

### Уже сделано ✅
- [x] Стек, БД, Docker, деплой
- [x] **§5 Модуль приёмки** (приёмка, ячейки, этикетки, перенос, sync названий WB)
- [x] Сборка FBS: кабинет, стикеры, ЧЗ, scan-print
- [x] **Счётчики WB = ЛК WB (delivery-v11)**
- [x] **Сборка FBS: список «Новые» = ЛК WB** (reconcile stale, sync при входе)
- [x] Поштучная отправка на сборку и в доставку (WB supplies API)
- [x] Фильтр складов SellerWarehouse (строгий: только включённые `wb_warehouse_id`)
- [x] Массовая «Все на сборку»
- [x] Архив заказов + опрос поставок в доставке для точного счётчика
- [x] **Кабинет селлера:** Statistics API, календарные периоды, стадии WB, отгрузки 4 недели + ₽
- [x] **Сборка FBS:** единый queryset «Новые», fix `shipped_missing`
- [x] **Тарифы селлера** в UI (`/sellers` → Тариф)
- [x] **Отгрузки WB:** все заказы из поставок (не только CRM)
- [x] **Админ `/billing`:** сводка по всем селлерам
- [x] **§9 Поставки** в «Сборке FBS» (лист → скан → ЧЗ → QR)
- [x] **§10 Списание остатков** при «В доставку», sync `done=true` **и доставке через ЛК WB**
- [x] **§7 Агент печати Xprinter** (`.exe` + `install-agent.bat` + `/print-agent`)
- [x] **Лист подбора:** отдельная кнопка, PDF A4, артикул WB + размер, одна поставка/склад
- [x] **Счётчик «В доставке» = ЛК WB** (delivery-v14, reconcile stale waiting)
- [x] **Приёмка в XL** (`/intake-xl`): автосохранение скана, контрольная точка, Excel, ячейки после WB, возобновление после applied, «Завершить приёмку» (`6af6be3`)
- [x] **Ozon FBS шаг 5** — кабинет селлера (вкладка Ozon) и `/billing` по отгрузкам Ozon
- [x] **Сборка WB «На сборке»:** лист подбора скрыт, активное окно баркода → ЧЗ → печать стикера (окно печати в жесте сканера, iframe-запас)

---

## Текущие проблемы и риски

| Проблема | Статус | Что делать |
|----------|--------|------------|
| Расхождение счётчиков CRM vs WB | ✅ **Решено** | delivery-v14 |
| Счётчик «В доставке» 303 vs 209 (ИП Мазирка) | ✅ **Решено** | live API `wb_count_delivery` + `reconcile_stale_delivery_orders` |
| Список «Новые» в сборке ≠ счётчик WB | ✅ **Решено** | reconcile_stale_new_orders + sync при входе |
| Остатки не списываются при доставке через ЛК WB | ✅ **Решено** | `supply_sync.py` + `deduct_pending_delivery_stock` |
| Админка без порта → 404 | ℹ️ | Только `:8080/admin` или `:8001/admin` |
| Заказы без ячейки (—) | ℹ️ | Сначала приёмка товара с тем же баркодом |
| WB_TOKEN_ENCRYPTION_KEY пустой | ⚠️ | Задать в `.env` на сервере |
| Печать Xprinter из браузера | ✅ | Агент на сервере: `http://5.129.243.246:8080/downloads/FulfillmentCRM-PrintAgent.exe` |
| **Сборка FBS: список заказов ≠ счётчик при выборе склада** | ✅ **Решено** | Строгий фильтр складов + `wb_new_order_ids` из WB `/orders/new` |
| **Кабинет селлера: 37 заказов за месяц** | ✅ **Решено** | Statistics API + `srid`, не Marketplace API |
| **Отгрузки: только CRM-заказы** | ✅ **Решено** | order-ids из WB API, индекс CRM+архив |
| **Админ `/billing` медленный** | 🟡 | Много запросов WB; нужен кэш/Celery |
| Печать стикера FBS после скана ЧЗ не открывалась | ✅ **Решено** | Окно печати в жесте Enter до ответа API; запас через iframe; лист подбора скрыт на «На сборке» |
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
| **24.08.2026** | **Кабинет селлера + Statistics API + отгрузки** | Ассистент |
| **24.08.2026** | **Тарифы + суммы отгрузок + админ `/billing`** | Ассистент |
| **24.08.2026** | **Аудит ТЗ vs код: операционка закрыта, очередь — §11 возвраты** | Ассистент |
| **25–26.08.2026** | **Доставка WB: списание из ЛК, счётчик 303→209, лист подбора, поставка/склад** | Ассистент |
| **27.08.2026** | **Приёмка в XL; возвраты убраны из очереди** | Ассистент |
| **27.08.2026** | **Ozon FBS: план + шаг 1 (каркас маркетплейса)** | Ассистент |
| **27.08.2026** | **Ozon FBS: склады, отправления, сборка скан/ship** | Ассистент |
| **27.08.2026** | **Ozon FBS шаг 3: онбординг каталога Ozon → ячейки** | Ассистент |
| **27.08.2026** | **Этикетка ячейки: одна 75×120, две зоны (номер + маркетплейс/ИП/баркод)** | Ассистент |
| **28.08.2026** | **Сборка: «нет в поставке» (красное окно) + сверка WB авто/скан + печать этикеток** | Ассистент |
| **29.08.2026** | **Приёмка в XL: возобновление скана, дельта WB, завершение сессии** | Ассистент |
| **29.08.2026** | **Ozon FBS: PDF-этикетка, ЧЗ, акт/ШК, Celery-синк, остатки на Ozon** | Ассистент |
| **29.08.2026** | **Ozon FBS шаг 5: кабинет селлера и `/billing` по Ozon** | Ассистент |

---

## Git-коммиты (основные, август 2026)
- `1c2e18a` — Sync assembly FBS counters (единый queryset «Новые»)
- `e9c72b4` — Remove `shipped_missing`, fix CRM/WB desync
- `ec14ee8` — Seller cabinet: calendar stats, WB stages, weekly shipments
- `6e4eabd` — Period comparison arrows/% in cabinet
- `ba66160` — Statistics API for order counts
- `c96624d` / `6022402` / `69ebd14` — Fix cabinet 500, zero counts, `_order_identity`
- `dadde9c` — Interactive weekly shipments (4 weeks)
- `4d5e4e4` — Seller tariff management (admin UI)
- `dbcfc6c` — Shipment amounts in seller cabinet
- `c75a9b7` — All WB supply orders for billing (not only CRM)
- `7d33a0f` — Admin billing dashboard `/billing`
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
- `0b67b58` — Print agent install-agent.bat
- `bf1c0a9` — FBS: delete order, pick list PDF, fix pick list generation
- `b193547` — Standalone pick list preview and PDF by warehouse
- `a243096` — One WB supply per warehouse; pick list with article and size
- `5555e25` — Stock deduction for orders sent to delivery via WB LK
- `c723f7b` — Fix delivery counter: complete+waiting from live API (delivery-v14)
- `a739e02` — Warehouse inventory with WB stock verification
- `d90766f` — Inventory UI: cell label print, barcode focus
- `2cdaeec` — Bulk assembly: batch WB supply orders in chunks of 100
- `8451972` — Marking retry after WB error, sticker number on errors, Chrome print
- `440585b` — Marking queue panels, background verify 3s, fast barcode→ЧЗ
- `6af6be3` — XL intake: resume scan after save/WB apply, delta stock, complete session (`0007_xl_intake_resume`)

---

**Конец документа PROGRESS.md**  
**Детали 25–26.08.2026:** [тз и прогрес/2026-08-25-26-сборка-fbs-доставка-остатки.md](тз%20и%20прогрес/2026-08-25-26-сборка-fbs-доставка-остатки.md)  
**Детали 27.08.2026 (Приёмка в XL):** [тз и прогрес/2026-08-27-приемка-xl.md](тз%20и%20прогрес/2026-08-27-приемка-xl.md)
