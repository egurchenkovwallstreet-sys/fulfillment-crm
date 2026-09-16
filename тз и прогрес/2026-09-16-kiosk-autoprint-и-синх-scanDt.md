# 16.09.2026 — Chrome автопечать FBS (белый экран) + синхронизация scanDt поставок

## 1. Проблема: белый экран при входе в сборку через ярлык autoprint

### Симптом
- CRM открыта через ярлык Chrome с `--kiosk-printing` и `?print_mode=kiosk`
- Сборка FBS → выбор селлера → страница рисуется ~1 сек → **весь экран белый**
- Без ярлыka (обычный Chrome) страница работает, но печать стикера требует Enter

### Причина
1. Chrome с `--kiosk-printing` печатает **без диалога** — любой `window.print()` на главной вкладке CRM сразу уходит на принтер
2. В `AssemblyPage.css` были правила `@media print`, которые **скрывали sidebar, шапку и весь контент сборки** — при срабатывании печати экран становился белым
3. Старый fallback печати через iframe мог вызывать `print()` на родительской вкладке
4. Защита `initKioskPrintGuard()` работала **только** если CRM «помнила» kiosk (`sessionStorage` после `?print_mode=kiosk`), а Chrome kiosk-режим активен **всегда** при запуске через ярлык

### Исправления

| Коммит | Что сделано |
|--------|-------------|
| `a287bd2` | Убран `@media print` из `AssemblyPage.css`; guard на main window; печать стикера через blob-popup вместо iframe; `data?.seller?.company_name` |
| `9f4c258` | **Защита печати включена всегда** (не только при sessionStorage kiosk); обработчик `beforeprint`; fix `data?.warehouses?.length` |

### Файлы
- `frontend/src/utils/printMode.ts` — `initKioskPrintMode`, `initKioskPrintGuard`, `markPrintSurfaceHtml`
- `frontend/src/utils/browserPrint.ts` — popup 58×40, `openPrintHolder`, blob fallback
- `frontend/src/utils/printService.ts` — сначала агент `:9123`, иначе browser popup
- `frontend/src/App.tsx` — вызов guard при старте
- `frontend/src/pages/AssemblySellerPage.tsx` — скан → popup → печать
- `frontend/public/downloads/install-kiosk-chrome.bat`, `.vbs`, `kiosk-chrome-manual.txt` — установка ярлыка

### Как должно работать (для склада)
1. Xprinter — **принтер по умолчанию** в Windows (58×40 мм)
2. Ярлык: `"C:\Program Files\Google\Chrome\Application\chrome.exe" --kiosk-printing http://5.129.243.246:8080/?print_mode=kiosk`
3. Открывать CRM **только через ярлык**, в **той же вкладке** переходить в сборку
4. В шапке сборки: **«Печать: Chrome (автопечать)»**
5. Скан баркода → стикер на принтер **без Enter**
6. После деплоя на ПК склада: **Ctrl+F5** (жёсткое обновление, иначе старый JS в кэше браузера)

### Деплой
```bash
cd /opt/fulfillment-crm && git pull && FULL_REBUILD=1 bash scripts/deploy.sh
```

---

## 2. Проблема: поставки «зависают» в «В доставке» после скана ШК на WB

### Симптом
- На WB в ЛК поставка отсканирована (есть время scanDt)
- В CRM в отчёте владельца: **ШК —**, счётчик «В доставке» не падает

### Причины (найдены 15–16.09.2026)
1. Импорт поставок после sync **сбрасывал** `wb_scanned_at`, если в list API WB не было `scanDt`
2. `_revert_premature_supply_scans` мог откатывать scan при ошибках API
3. На вкладке «В доставке» убрали частый sync (регрессия `717d6c6`)
4. Счётчик селлеров брал `wb_in_delivery_q()` вместо заказов без scanDt

### Исправления

| Коммит | Что сделано |
|--------|-------------|
| `717d6c6` | Celery очереди, фоновый sync |
| `24730c7` | Detail API fallback для scanDt; восстановлен sync на вкладке «В доставке» |
| `51f1223` | Быстрый режим `delivery` sync |
| `c8db8b6` | Счётчик селлеров = delivery stage count |
| `50c99d4` | Массовый scanDt sync каждые 2 мин (Celery beat) |
| `45c7855` | **Корень:** import не отменяет scanDt; `repair_supply_scans` management command |

### Ручной ремонт на сервере
```bash
docker compose exec web python manage.py repair_supply_scans
docker compose exec web python manage.py repair_supply_scans --company "Семенова"
```

---

## 3. Проверка после деплоя

| Проверка | Ожидание |
|----------|----------|
| Ярлык autoprint → сборка селлера | Страница **не белеет** |
| Шапка сборки | «Печать: Chrome (автопечать)» |
| F12 Console при белом экране | Нет красных ошибок; может быть «Печать основного окна CRM заблокирована» |
| `docker compose exec frontend sh -c 'grep -r initKioskPrintGuard /usr/share/nginx/html/assets/ \| head'` | Находит строку в бандле |
| scanDt после скана на WB | Через 2–5 мин счётчик «В доставке» падает; в отчёте **ШК ✓** |
