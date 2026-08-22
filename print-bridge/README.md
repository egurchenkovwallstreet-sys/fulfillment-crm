# Fulfillment CRM — Агент печати

Локальная программа для **Windows** на ПК склада. Печать стикеров FBS на Xprinter 365/370 **без диалога Chrome** (< 2 сек).

## Для пользователя склада

1. В CRM откройте **«Агент печати»** в меню → **Скачать агент (.exe)**.
2. Запустите `FulfillmentCRM-PrintAgent.exe` — иконка **FF** в трее Windows.
3. В меню трея включите **«Автозапуск Windows»**.
4. В **Сборке FBS** в шапке: **«Печать: Xprinter»**.

Настройки: `%APPDATA%\FulfillmentCRM\PrintAgent\config.json`

Проверка: http://127.0.0.1:9123/health

## Для разработчика — сборка .exe

Требуется **Windows** + Python 3.11+.

```bat
cd print-bridge
build.bat
```

Результат:
- `print-bridge\dist\FulfillmentCRM-PrintAgent.exe`
- копия в `frontend\public\downloads\` для скачивания из CRM

После сборки на сервере: `git pull && bash scripts/deploy.sh` (если exe залит на сервер вручную).

## Разработка без сборки

```bat
cd print-bridge
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python agent_main.py
```

Или консольный режим API: `venv\Scripts\python server.py`

## API

| Метод | URL | Описание |
|-------|-----|----------|
| GET | `/health` | Статус, имя принтера |
| GET | `/printers` | Список принтеров Windows |
| POST | `/print` | `{ "job_type": "fbs_sticker", "image_base64": "..." }` |
| GET/POST | `/config` | Настройки |

Типы заданий: `fbs_sticker` (58×40), `supply_sticker` (58×40), `cell_label` (75×120).

Подробнее: `docs/print-agent.md`
