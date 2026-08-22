# Print Bridge — Xprinter 365/370

Локальный сервис на **ПК склада** (Windows). CRM шлёт стикер FBS / QR поставки напрямую на принтер **без диалога Chrome** (< 2 сек).

## Установка (один раз)

1. На ПК склада установите [Python 3.11+](https://www.python.org/downloads/) (галочка «Add to PATH»).
2. Подключите Xprinter 365 или 370 по USB, установите драйвер из комплекта.
3. В Windows назначьте Xprinter **принтером по умолчанию** (или укажите имя в `config.json`).
4. Скопируйте папку `print-bridge` с репозитория на ПК (или `git pull` в `C:\fulfillment-crm\print-bridge`).
5. Запустите **`install.bat`** — создаст venv и поднимет сервис на `http://127.0.0.1:9123`.

## Автозапуск

Создайте ярлык на `install.bat` в папке автозагрузки Windows:
`Win+R` → `shell:startup`

## Проверка

Откройте в браузере: http://127.0.0.1:9123/health

Должно быть: `{"ok": true, "printer": "Xprinter ..."}`

## CRM

Откройте сборку FBS с этого же ПК. В шапке:
- **«Печать: Xprinter»** — мост работает
- **«Печать: Chrome»** — запустите `install.bat`

## config.json

```json
{
  "default_printer": "Xprinter XP-365B",
  "port": 9123
}
```

Список принтеров: `GET http://127.0.0.1:9123/printers`
