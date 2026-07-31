# Контекст проекта PostParserApp

## Текущее состояние

- Проект называется PostParserApp.
- Рабочий VPS использует Flask, Telethon, Gunicorn, Nginx и systemd.
- Служба на VPS называется `telegram-parser.service`.
- Рабочая папка на VPS: `/opt/telegram-parser`.
- Внешний домен: `tg-parser.proactivum.ru`.
- Python API поддерживает Telegram и Instagram.
- Доступны маршруты `/health`, `/parse`, `/instagram/parse`, `/instagram/connect` и `/instagram/callback`.
- Instagram-токен пока хранится на VPS отдельно от Git.
- Google Apps Script пока содержит VK-парсер, интерфейс и запись результатов в Google Sheets.
- Код Google Apps Script сохранён в каталоге `apps-script-archive`.
- Секреты находятся только в переменных окружения и приватных файлах.
- В исправленной логике VK `offset` увеличивается только один раз через `WALL_PAGE_SIZE`.

## Целевое состояние и порядок миграции

- Цель — полностью перенести интерфейс, настройки, VK-парсер, результаты и экспорт на VPS.
- GitHub должен стать основным источником кода.
- Рабочий VPS пока нельзя ломать или автоматически обновлять.
- Архитектуру нужно постепенно разделить на модули.
- Сначала серверная версия создаётся параллельно действующему Google Apps Script.
- Google Apps Script отключается только после полного тестирования серверной версии.
