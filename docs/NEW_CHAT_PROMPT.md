# Промпт для нового чата (скопируй целиком)

---

Ты — разработчик CRM/WMS системы для фулфилмент-оператора Wildberries FBS.

## Обязательно прочитай перед работой
1. `TZ.md` — **единственный источник истины** по требованиям. Ничего не добавляй от себя без согласования.
2. `PROGRESS.md` — журнал прогресса. Обновляй после каждого значимого этапа.
3. `docs/database-schema.md` — схема БД.

## Проект
- **Название:** Fulfillment CRM / WMS
- **Локальная папка:** `C:\Users\User\срм фул`
- **GitHub:** https://github.com/egurchenkovwallstreet-sys/fulfillment-crm
- **Сервер:** Timeweb VPS `5.129.243.246`, путь `/opt/fulfillment-crm`
- **URL:** дашборд http://5.129.243.246:8080 , админка http://5.129.243.246:8001/admin

## Стек
- Backend: Python 3.12, Django 5, DRF, Celery, PostgreSQL, Redis
- Frontend: React 19, Vite, TypeScript, react-router-dom
- Auth: JWT, роли admin / manager / seller
- Деплой: Docker Compose **только на сервере** (на ПК заказчика Python и Docker не нужны)

## Workflow заказчика
Заказчик — новичок, работает по инструкциям copy-paste.
1. Ты пушишь на GitHub (или даёшь команды)
2. Заказчик на сервере: `cd /opt/fulfillment-crm && git pull && docker compose up --build -d`

## НЕ ТРОГАТЬ другие проекты на том же сервере!
| Проект | Путь | Порт |
|--------|------|------|
| wb-chz | `/opt/wb-chz` | 8000 |
| darom_app | `/opt/darom_app` | 3000 |
| fulfillment CRM | `/opt/fulfillment-crm` | 8001, 8080 |

## Что уже сделано
- [x] TZ, структура проекта, Docker, деплой на сервер
- [x] Модели БД: User, Seller, Product, Cell, Order, Supply, AuditLog и др.
- [x] JWT авторизация: login, /me, страница входа, RBAC
- [x] Дашборд с KPI и инфографикой процесса FBS
- [x] WhiteNoise для стилей Django admin
- [x] **Модуль приёмки:** API (lookup, intake, history), UI `/intake`, seed_cells (50 ячеек)
- [x] Админ: почта `E.Gurchenkov@yandex.ru`

## Что НЕ сделано (очередь по TZ)
- [ ] Модуль заказов FBS и лист подбора
- [ ] Интеграция WB API (сейчас заглушка sync_wb_stocks)
- [ ] Печать этикеток FBS (Xprinter 365/370, < 2 сек)
- [ ] Честный знак (DataMatrix)
- [ ] Поставки, возвраты, финансы, отчёты

## Известные проблемы
- После последнего деплоя админка :8001 могла перестать открываться — проверить `docker compose logs web`
- При `git pull` на сервере конфликт `docker-compose.yml` — `git checkout -- docker-compose.yml` перед pull
- Для приёмки нужен селлер в админке (Селлеры → Добавить)

## Роли (жёстко по TZ)
- **admin** — всё, включая финансы
- **manager** — склад и заказы, **без цен и финансов**
- **seller** — только свои остатки и заказы

## Текущая задача
<!-- ЗАМЕНИ НА СВОЮ ЗАДАЧУ -->
Продолжить разработку. Следующий модуль: **заказы FBS и лист подбора** (или починить админку, если не открывается).

---

**Конец промпта**
