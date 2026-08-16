# Развёртывание на сервере (Timeweb VPS)

**Важно:** этот проект полностью отделён от других:
- `wb-chz` → `/opt/wb-chz`, порт **8000**
- `darom_app` → `/opt/darom_app`, порт **3000**
- **fulfillment CRM** → `/opt/fulfillment-crm`, порт **8001**

Никакие файлы существующих проектов не затрагиваются.

## Работа БЕЗ Docker на вашем ПК (рекомендуется)

На компьютере нужны только:
- **Cursor** (редактор кода)
- **Git** (или GitHub Desktop)
- **Node.js** — только если хотите смотреть frontend локально (необязательно)

**Docker на ПК не нужен.** Docker крутится только на сервере (как у wb-chz).

### Схема работы

```
Ваш ПК (Cursor)  →  git push  →  GitHub  →  git pull на сервере  →  docker compose на VPS
```

### На вашем ПК

1. Редактируете код в Cursor
2. Коммит и push на GitHub:

```powershell
cd "C:\Users\User\срм фул"
git add .
git commit -m "описание изменений"
git push
```

### На сервере (SSH, как для wb-chz)

```bash
cd /opt/fulfillment-crm
git pull
docker compose up --build -d
```

Проверка: откройте в браузере `http://ВАШ_IP:8001/admin` или домен через nginx.

### Frontend без Docker на ПК (опционально)

Если хотите интерфейс локально, а API на сервере — в `frontend/.env`:

```
VITE_API_URL=http://ВАШ_IP:8001
```

И `npm run dev` в папке `frontend`. Иначе — смотрите всё прямо на сервере.

---

- Docker + Docker Compose
- Git
- Nginx (для домена, опционально на первом этапе)

## Первый деплой

```bash
# На сервере (SSH)
sudo mkdir -p /opt/fulfillment-crm
sudo chown $USER:$USER /opt/fulfillment-crm
cd /opt/fulfillment-crm

git clone https://github.com/YOUR_USER/fulfillment-crm.git .
cp .env.example .env
nano .env   # SECRET_KEY, ALLOWED_HOSTS, POSTGRES_PASSWORD
```

В `.env` обязательно задать:
```
SECRET_KEY=длинная-случайная-строка
DEBUG=false
ALLOWED_HOSTS=your-domain.ru,localhost,127.0.0.1
POSTGRES_PASSWORD=надёжный-пароль
```

Запуск:

```bash
docker compose up --build -d
```

Проверка:

```bash
docker compose ps
curl http://127.0.0.1:8001/api/auth/token/   # должен ответить (405 или JSON)
```

Создание администратора:

```bash
docker compose exec web python manage.py createsuperuser
```

## Обновление (как wb-chz)

```bash
cd /opt/fulfillment-crm
git pull
docker compose up --build -d
```

## Nginx (пример)

Отдельный конфиг, не трогая chz-wb.ru и darom:

```nginx
server {
    listen 80;
    server_name fulfillment.your-domain.ru;

    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Frontend (React) после сборки можно отдавать через тот же nginx или отдельный поддомен.

## Локальная разработка (без Python на ПК)

```powershell
cd "C:\Users\User\срм фул"
copy .env.example .env
docker compose up --build -d
```

API: http://localhost:8001  
Admin: http://localhost:8001/admin

Frontend (отдельно, нужен только Node.js):

```powershell
cd frontend
npm install
npm run dev
```

UI: http://localhost:5173

## Полезные команды

```bash
docker compose logs -f web          # логи API
docker compose logs -f worker       # логи Celery
docker compose exec web python manage.py shell
docker compose down               # остановить (данные в volumes сохранятся)
```
