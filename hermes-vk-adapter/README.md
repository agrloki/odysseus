# VK Messenger Platform Adapter для Hermes Agent

Плагин-адаптер, подключающий Hermes Agent к **VK Messenger** (ВКонтакте) — самой популярной платформе обмена сообщениями в России.

---

# VK Messenger Platform Adapter for Hermes Agent

A community-contributed plugin adapter that connects Hermes Agent to **VK Messenger** (VKontakte), the most popular messaging platform in Russia.

---

## Возможности / Features

| Feature | Status |
|---------|--------|
| Текстовые сообщения / Text messages (send/receive) | ✅ |
| Индикатор печати / Typing indicator | ✅ |
| Inline-клавиатуры (approve/deny/confirm) / Inline keyboards | ✅ |
| Загрузка изображений / Image upload | ✅ |
| Загрузка документов / Document upload | ✅ |
| Голосовые сообщения / Voice messages (send/receive) | ✅ |
| Приём изображений/документов/аудио / Receive media from users | ✅ |
| Авто-разбивка длинных сообщений (4096 символов) / Message splitting | ✅ |
| HTML → .txt (VK блокирует .html) / VK blocks .html, auto-renamed | ✅ |
| REST API polling (без публичного URL) / No public URL needed | ✅ |
| Групповые чаты / Group chat support | ✅ |

---

## Архитектура / Architecture

```
Пользователь VK → Серверы VK → REST polling (5s) → VKAdapter → Hermes Agent
                              ← messages.send       ←
```

Адаптер использует **двухэтапный REST API polling** / The adapter uses **two-step REST API polling**:

1. `messages.getConversations` — обнаружение активных бесед / detects active conversations
2. `messages.getHistory` — получение ВСЕХ новых сообщений / fetches ALL new messages

Каждое сообщение обрабатывается как отдельная `asyncio.Task`, что предотвращает блокировки при ожидании подтверждения опасных команд / Each message is dispatched as an independent task to prevent deadlocks during approval flows.

---

## Установка / Installation

### 1. Поместите файлы в директорию плагинов / Place files in plugins directory

```bash
mkdir -p ~/.hermes/plugins/vk/
cp adapter.py plugin.yaml __init__.py ~/.hermes/plugins/vk/
```

### 2. Создайте сообщество ВКонтакте / Create a VK Community

- Зайдите в **vk.com/groups** → Создайте сообщество (любой тип, можно закрытое)
- **Управление** → **Сообщения** → Включите сообщения сообщества
- **Управление** → **Работа с API** → Создайте токен → включите права **Сообщения**

### 3. Настройте Hermes / Configure Hermes

Добавьте в `~/.hermes/.env`:

```bash
VK_TOKEN=vk1.a.....your_token.....
VK_GROUP_ID=123456789
```

Включите в конфиге / Enable in config:

```bash
hermes config set gateway.platforms.vk.enabled true
```

### 4. Перезапустите шлюз / Restart Gateway

```bash
systemctl --user restart hermes-gateway
```

---

## Параметры конфигурации / Configuration Reference

| Env Var | Required | Description |
|---------|----------|-------------|
| `VK_TOKEN` | ✅ | Токен API сообщества / VK community API token |
| `VK_GROUP_ID` | ✅ | ID сообщества / Numeric community ID |
| `VK_API_VERSION` | ❌ | Версия API (по умолчанию 5.199) / API version (default: 5.199) |
| `VK_ALLOWED_USERS` | ❌ | ID пользователей, которым разрешено использовать бота / Allowed user IDs |
| `VK_ALLOW_ALL_USERS` | ❌ | Разрешить всем пользователям / Allow all users (true/false) |
| `VK_HOME_CHANNEL` | ❌ | Peer ID для доставки уведомлений / Peer ID for cron delivery |

---

## Особенности VK / VK-Specific Behaviour

- **Inline-кнопки в групповых чатах**: VK добавляет `@упоминание` бота к тексту кнопки. Адаптер обрабатывает это автоматически / VK prepends @mention in group chats, handled transparently.
- **Форматирование**: VK не поддерживает Markdown в сообщениях сообществ. Адаптер удаляет `**жирный**`, `*курсив*`, `` `код` `` / VK bots don't render Markdown, the adapter strips it.
- **Лимит сообщений**: VK ограничивает 4096 символов. Длинные сообщения автоматически разбиваются / VK enforces 4096 chars, auto-split with (1/N) suffixes.
- **HTML-файлы**: VK блокирует загрузку `.html` — они переименовываются в `.txt` / VK blocks .html uploads, renamed to .txt.

---

## Структура кода / Code Overview

| File | Lines | Purpose |
|------|-------|---------|
| `plugin.yaml` | 35 | Метаданные плагина / Plugin metadata |
| `__init__.py` | 3 | Экспорт `register()` / Exports register() |
| `adapter.py` | ~1150 | Полная реализация адаптера / Full adapter implementation |

---

**Автор / Author:** Igor Borges  
**Лицензия / License:** MIT (same as Hermes Agent)  
**Статус / Status:** Production-tested since June 2026
