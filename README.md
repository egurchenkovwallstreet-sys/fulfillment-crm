# Fulfillment CRM / WMS

B2B-система для фулфилмент-оператора. Автоматизация работы с селлерами Wildberries по модели FBS.

**Документация:**
- [TZ.md](./TZ.md) — техническое задание (единственный источник истины)
- [PROGRESS.md](./PROGRESS.md) — журнал прогресса разработки
- [тз и прогрес/](./тз%20и%20прогрес/) — детальные отчёты по этапам разработки
- [docs/database-schema.md](./docs/database-schema.md) — схема базы данных
- [docs/deploy.md](./docs/deploy.md) — развёртывание на сервере

## Стек

| Компонент | Технология |
|-----------|------------|
| Backend | Python 3.12, Django 5, Django REST Framework |
| БД | PostgreSQL 16 |
| Очереди | Celery + Redis |
| Frontend | React 18 + Vite + TypeScript |
| Auth | JWT + RBAC (admin / manager / seller) |
| Запуск | **Docker Compose** (Python на ПК не нужен) |

## Структура проекта

```
срм фул/
├── TZ.md
├── PROGRESS.md
├── docker-compose.yml      # web + worker + beat + db + redis
├── .env.example
├── backend/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── manage.py
│   ├── requirements.txt
│   └── apps/
├── frontend/               # React SPA
└── docs/
```

## Быстрый старт

### Вариант A — без Docker на ПК (рекомендуется)

На компьютере: только Cursor + Git. Docker — **только на сервере** (как wb-chz).

1. Создайте репозиторий на GitHub
2. Залейте код: `git push`
3. На сервере: `git clone` в `/opt/fulfillment-crm` → `docker compose up --build -d`
4. Работаете: правки в Cursor → `git push` → на сервере `git pull` + `docker compose up --build -d`

Подробно: [docs/deploy.md](./docs/deploy.md)

### Вариант B — Docker на ПК (для локальной отладки)

https://www.docker.com/products/docker-desktop/

### 2. Запустить весь backend

```powershell
cd "C:\Users\User\срм фул"
copy .env.example .env
docker compose up --build -d
```

Первый запуск займёт несколько минут (сборка образа, миграции БД).

### 3. Создать администратора

```powershell
docker compose exec web python manage.py createsuperuser
```

### 4. Проверить

- API: http://localhost:8001
- Admin: http://localhost:8001/admin

### 5. Frontend (нужен только Node.js)

```powershell
cd frontend
npm install
npm run dev
```

UI: http://localhost:5173 (прокси на API :8001)

## Сервисы Docker

| Сервис | Контейнер | Порт |
|--------|-----------|------|
| web (Django) | fulfillment_web | 127.0.0.1:**8001** |
| worker (Celery) | fulfillment_worker | — |
| beat (Celery) | fulfillment_beat | — |
| PostgreSQL | fulfillment_db | внутренний |
| Redis | fulfillment_redis | внутренний |

> Порт **8001** выбран специально — на том же сервере wb-chz использует **8000**.

## Роли (из ТЗ)

| Роль | Доступ |
|------|--------|
| **admin** | Полный доступ, финансы, селлеры, товары |
| **manager** | Склад и заказы, **без финансов** |
| **seller** | Только свои остатки и заказы |

## Деплой на сервер

См. [docs/deploy.md](./docs/deploy.md). Путь на сервере: `/opt/fulfillment-crm` (отдельно от wb-chz и darom).

## Полезные команды

```powershell
docker compose ps                    # статус
docker compose logs -f web           # логи
docker compose down                  # остановить
docker compose up --build -d         # пересобрать и запустить
```
