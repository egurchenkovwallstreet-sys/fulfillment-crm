# Агент печати Fulfillment CRM (решение зафиксировано 22.08.2026)

## Выбор заказчика

**Вариант A — брендированный агент `.exe`** на ПК склада (Windows).

Без ручной установки Python на рабочих местах. Один файл установки / один клик «Установить агент печати».

## Зачем

Браузер **не может** печатать на USB Xprinter 365/370 без диалога Chrome. Для сборки FBS нужно:

- скан баркода → стикер на принтере **< 2 сек**;
- без подтверждения «Печать» в Chrome.

Лист подбора (PDF A4) и этикетки ячеек (75×120) могут оставаться через браузер с подтверждением.

## Архитектура

```
CRM (браузер)  --HTTP POST-->  localhost:9123  --GDI-->  Xprinter USB
```

Прототип API уже в `print-bridge/server.py`. Фронт: `printService.ts` → сначала мост, иначе fallback Chrome.

| Endpoint | Назначение |
|----------|------------|
| `GET /health` | Проверка агента, имя принтера |
| `GET /printers` | Список принтеров Windows |
| `POST /print` | `{ job_type, image_base64 }` → печать PNG |
| `GET/POST /config` | `default_printer`, порт |

Типы заданий: `fbs_sticker` (58×40), `supply_sticker` (58×40), `cell_label` (75×120).

## Требования к `.exe`

1. **Установка:** один инсталлятор (Inno Setup / NSIS) или portable `.exe`; без Python на ПК.
2. **Брендинг:** название «Fulfillment CRM — Агент печати», иконка продукта.
3. **Автозапуск:** служба Windows или трей-иконка + автозагрузка.
4. **Порт:** `127.0.0.1:9123` (как в прототипе).
5. **CORS:** разрешить запросы с origin CRM (`http://5.129.243.246:8080` и будущий HTTPS-домен).
6. **Принтер:** по умолчанию — системный; выбор в `config.json` или мини-настройке при первом запуске.
7. **Сборка:** PyInstaller / cx_Freeze из `print-bridge/` (Flask + Pillow + pywin32).

## UX на ПК склада

1. CRM → **Агент печати** → скачать **`FulfillmentCRM-PrintAgent-portable.zip`** + **`install-agent.bat`** в одну папку.
2. Запустить **install-agent.bat** (ждать до 90 сек на старых ПК).
3. Иконка **FF** в трее, в сборке FBS — **«Печать: Xprinter»**.
4. Скан → автопечать стикера.

**Старые / медленные ПК:** используйте **portable.zip** (папка), не onefile `.exe` — первый запуск onefile распаковывается 30–60 сек и установщик мог не дождаться.

**Visual C++:** нужен [VC++ Redistributable x64](https://aka.ms/vs/17/release/vc_redist.x64.exe). `install-agent.bat` проверяет и открывает ссылку.

**Журнал:** `%APPDATA%\FulfillmentCRM\PrintAgent\agent.log` и `%TEMP%\FulfillmentCRM-PrintAgent-bootstrap.log`

## Запасной путь без агента: Chrome `--kiosk-printing`

Если агент не ставится (или антивирус блокирует exe):

1. Xprinter — **принтер по умолчанию** в Windows (58×40)
2. CRM → **Агент печати** → скопировать строку для ярлыка Chrome (без скачивания .bat/.vbs)
3. ПКМ на рабочем столе → Создать → Ярлык → вставить строку → имя **Fulfillment CRM (autoprint)**
4. Открывать CRM **только через этот ярлык** (не обычный Chrome)

Текстовая инструкция: `kiosk-chrome-manual.txt` (антивирус обычно не блокирует).

Chrome с флагом `--kiosk-printing` печатает на default printer **без диалога Enter**.

В шапке сборки: «Печать: Chrome (автопечать)».

## Этапы реализации

| # | Задача | Статус |
|---|--------|--------|
| 1 | Прототип API (`print-bridge/`) | ✅ |
| 2 | Интеграция CRM (`printService.ts`, индикатор в сборке) | ✅ |
| 3 | Сборка `.exe` (PyInstaller), `build.bat` | ✅ |
| 3b | **CI GitHub Actions** — сборка без Python на ПК разработчика | ✅ |
| 4 | Трей, автозапуск, config в AppData | ✅ |
| 5 | Страница «Агент печати» в CRM + скачивание | ✅ |
| 6 | Portable zip для старых ПК, VC++ check, bootstrap log | ✅ |
| 7 | Подпись кода (опционально, для доверия Windows SmartScreen) | ⬜ |

## Сборка без Python на вашем ПК

Workflow: `.github/workflows/build-print-agent.yml`

1. GitHub → **Actions** → **Build Print Agent** → **Run workflow**
2. Скачать артефакт `FulfillmentCRM-PrintAgent` (zip + onefile exe)
3. Положить на сервер:
   - `frontend/public/downloads/FulfillmentCRM-PrintAgent-portable.zip`
   - `frontend/public/downloads/FulfillmentCRM-PrintAgent-onefile.exe` (опционально)
   → `bash scripts/deploy.sh`

## Не в scope агента

- Сетевой принтер без локального агента (отдельная настройка Windows).
- Печать с Mac/Linux (только Windows + Xprinter).
