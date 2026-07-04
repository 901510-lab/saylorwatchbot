# Локальная AI-поддержка: Outlook + Evolution + Ollama

Почта поддержки: **SaylorWatch@outlook.com**

Цель: автоответы через Graph + Ollama; Telegram — только сложные письма и еженедельный отчёт.  
**Evolution** — просмотр и ручная отправка по эскалациям.  
JustRunMy **не нужен** — агент на вашем ПК.

---

## Архитектура

```
Outlook.com (облако — письма копятся пока ПК off)
       ↓ IMAP/SMTP
┌──────────────────┬─────────────────────────────┐
│ Evolution        │ scripts/email_support_agent │
│ (2-й аккаунт)    │ + Ollama + Telegram → admin │
└──────────────────┴─────────────────────────────┘
```

Bridge **не нужен** — прямой IMAP к Microsoft.

---

## Стоимость: **0 €/мес**

Outlook Free + Evolution + Ollama + Telegram.

---

## Шаг 1 — Включить IMAP в Outlook (в браузере)

1. Откройте [outlook.live.com](https://outlook.live.com) под **SaylorWatch@outlook.com**
2. **Настройки** (⚙) → **Почта** → **Пересылка и IMAP**
3. Включите **«Разрешить устройствам и приложения использовать IMAP»** → **Сохранить**

Без этого шага клиенты и скрипт не подключатся.

---

## Шаг 2 — Evolution (✅ у вас работает)

Личный ящик отдельно — **SaylorWatch@outlook.com** вторым аккаунтом.

1. `sudo apt install evolution gnome-keyring seahorse`
2. **Файл → Создать → Учётная запись почты**
3. Email: `SaylorWatch@outlook.com`, снять «Искать настройки автоматически»
4. **IMAP** + **OAuth2 (Outlook)** — не Exchange/EWS, не «Обычный пароль»
5. Серверы: `outlook.office365.com:993` SSL, `smtp-mail.outlook.com:587` STARTTLS
6. Пройти окно Microsoft до `none-local://`

Если OAuth снова отменяется: `evolution --force-shutdown`, установить `gnome-keyring`, перезагрузка ПК.

**Thunderbird** тоже подходит (OAuth2), но на вашей системе надёжнее Evolution.

### Проверка

Тестовое письмо на `SaylorWatch@outlook.com` → **Входящие** в Evolution.

---

## Шаг 3 — Ollama

```bash
ollama pull qwen2.5:3b   # или llama3.2 — см. OLLAMA_MODEL в env
curl http://127.0.0.1:11434/api/tags
```

---

## Шаг 4 — Скрипт агента

```bash
cd ~/SaylorWatchBot
# scripts/email_support.env уже создан из шаблона — допишите пароль и chat id
nano scripts/email_support.env

python3 scripts/email_support_agent.py --dry-run
python3 scripts/email_support_agent.py --startup
```

### OAuth2 (рекомендуется)

Microsoft **не принимает** App Password для новых `@outlook.com`. Нужны **два** OAuth-токена:

| Действие | Команда | Файл токена |
|----------|---------|-------------|
| **Читать** (IMAP) | `--oauth-login` | `scripts/.email_oauth.json` |
| **Отправлять** (Graph) | `--oauth-graph` | `scripts/.email_graph_oauth.json` |

```bash
cd ~/SaylorWatchBot
# в email_support.env: MAIL_AUTH=oauth, EMAIL_SEND_METHOD=graph
python3 scripts/email_support_agent.py --oauth-login   # браузер → redirect URL
python3 scripts/email_support_agent.py --oauth-graph   # microsoft.com/devicelogin → код
python3 scripts/email_support_agent.py --test-send ваш@email.com
python3 scripts/email_support_agent.py --startup
```

**Почему Graph, а не SMTP:** Microsoft блокирует SMTP на личных ящиках (`SmtpClientAuthentication disabled`). Graph API `Mail.Send` отправляет с **того же** `SaylorWatch@outlook.com` без SMTP.

Evolution по-прежнему для просмотра и ручной отправки; скрипт шлёт FAQ-ответы через Graph автоматически.

### Запасной вариант — Gmail SMTP

Если Graph недоступен, создайте ящик Gmail + App Password и в env:

```env
EMAIL_SEND_METHOD=graph,gmail
GMAIL_USER=SaylorWatch@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

Письма уйдут с Gmail-адреса (или настройте «Отправить от имени» в Gmail).

### `scripts/email_support.env`

```env
MAIL_AUTH=oauth
MAIL_USER=SaylorWatch@outlook.com
TELEGRAM_BOT_TOKEN=...      # = BOT_TOKEN из .env бота
TELEGRAM_ADMIN_CHAT_ID=...  # = ваш личный chat id (/chatid в боте)
EMAIL_AGENT_MODE=auto
OLLAMA_MODEL=qwen2.5:3b
```

> **Evolution** и **скрипт** — оба через OAuth2. App Password больше не нужен.

### Режим **auto** (основной)

| Тип письма | Действие | Telegram |
|------------|----------|----------|
| FAQ, help, команды бота (playbook / уверенный Ollama) | полный авто-ответ через Graph | **нет** |
| AI не уверен (UNCERTAIN / неверные команды / Ollama down) | подтверждение клиенту | **да** (текст письма) |
| Refund, legal, GDPR, партнёрство… | подтверждение + черновик в Evolution | **да** |
| Ошибка отправки | очередь retry | **да** |

Еженедельно в Telegram — **отчёт по цифрам** (без AI-саммари):

```
📊 SaylorWatch — отчёт за неделю
Поступило: 3 письма.
Обработано: 3 письма.
```

### Другие режимы

| Режим | Поведение |
|-------|-----------|
| **draft** | AI → черновик в **Drafts** (без Telegram) |
| **suggest** | только файл на диске |
| **send** | авто-отправка всего ⚠️ |

Повторная обработка письма:
```bash
python3 scripts/email_support_agent.py --reprocess
```

---

## ПК периодически выключен

Письма копятся в Outlook; при включении ПК:

```bash
python3 scripts/email_support_agent.py --startup
```

Обрабатывает необработанные за **30 дней** + weekly саммари если >7 дней.

### Автозапуск (Linux)

```bash
chmod +x scripts/install_email_systemd.sh
./scripts/install_email_systemd.sh
```

| Unit | Когда |
|------|-------|
| `saylorwatch-email-startup.service` | при входе → `--startup` |
| `saylorwatch-email-poll.timer` | каждые 30 мин пока ПК on |

---

## JustRunMy (бот)

```env
SUPPORT_EMAIL=SaylorWatch@outlook.com
```

Restart после смены. Проверка: `/disclaimer` → блок «📬 Поддержка».

---

## Безопасность

1. Только **draft** первые 2–4 недели
2. `email_support.env` **не в git**
3. AI не обещает refund / ручной Premium
4. Сложные кейсы — вы вручную

---

## Файлы

| Файл | Назначение |
|------|------------|
| `scripts/email_support_agent.py` | агент |
| `scripts/email_support.example.env` | шаблон (Outlook) |
| `scripts/email_support.env` | ваш конфиг |
| `scripts/.email_support_state.json` | обработанные UID |
