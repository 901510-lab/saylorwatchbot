# Тарифы SaylorWatchBot (День 16)

Документ фиксирует **Free vs Premium** перед реализацией оплаты (Дни 17–20).
Код-источник истины: `subscription_plans.py`.

---

## Free — $0

Для знакомства с ботом и отслеживания **Strategy** без полного whale-suite.

| Возможность | Free |
|-------------|------|
| Алерты Strategy (покупка / продажа BTC) | ✅ с задержкой **~30 мин** |
| Image-карточки к алертам | ❌ (только текст) |
| Алерты компаний (Tesla, MARA, Block…) | ❌ |
| Алерты ETF-потоков (IBIT, FBTC, GBTC, ARKB) | ❌ |
| Мониторинг strategy.com (press / purchases) | ❌ |
| `/holdings`, `/stats`, `/buy`, `/status` | ✅ Strategy |
| `/whales` | ✅ топ **5** (без ETF AUM, если нет API-ключа на сервере) |
| **Weekly Digest** — еженедельная PNG-сводка | ❌ |
| `/donate`, `/disclaimer`, `/help` | ✅ |

**Задержка 30 мин** — free получает тот же сигнал, что и premium, но позже (публикация в канал / DM). Premium — мгновенно.

---

## Premium — $5–10 / мес (ориентир **$7**)

Полный **multi-whale** мониторинг и визуальные карточки.

| Возможность | Premium |
|-------------|---------|
| Алерты Strategy | ✅ **мгновенно** |
| Image-карточки (hero / compact, цвета по типу) | ✅ |
| Алерты **5 компаний** (CoinGecko treasury) | ✅ |
| Алерты **4 ETF** (дневные потоки, SoSoValue / Farside) | ✅ |
| strategy.com (пресс / purchases) | ✅ |
| `/whales` | ✅ топ **10** + ETF AUM |
| **Weekly Digest** — PNG-сводка в DM (**вс 12:00 NY**) + `/weekly` | ✅ |
| Ранний доступ к новым источникам (on-chain, gov…) | ✅ по мере добавления |

---

## Что остаётся бесплатным навсегда

- Базовые команды Strategy (`/holdings`, `/stats`, `/status`)
- Юридический `/disclaimer`
- Донаты `/donate` (не тариф, а поддержка сервера)

---

## Каналы доставки (план)

| Аудитория | Куда идут алерты |
|-----------|------------------|
| Admin (`X_CHAT_ID`) | Всё сразу (как сейчас) — для отладки и канала |
| Premium subscriber | DM бота, instant + карточки + **Weekly Digest** (вс **12:00 NY**) |
| Free user | DM или публичный канал, delay, без карточек для non-Strategy |

> **С Day 19:** алерты расходятся по тарифу — admin + Premium (instant, карточки) + Free Strategy (текст, ~30 мин delay). Гейтинг: `ENABLE_SUBSCRIPTION_GATING=true`.

---

## Связь с `entities.json`

| entity_id | Free alert | Premium alert |
|-----------|------------|---------------|
| strategy | ✅ delayed | ✅ instant + card |
| tesla, block, marathon, riot, metaplanet | ❌ | ✅ + card |
| ibit, fbtc, gbtc, ark | ❌ | ✅ + card |

---

## Оплата (День 18)

Premium оплачивается **Telegram Stars** (валюта `XTR`):

| Параметр | По умолчанию |
|----------|--------------|
| Цена | **350 ⭐** (`PREMIUM_STARS`) |
| Период | **30 дней** (`PREMIUM_BILLING_DAYS`) |
| Команда | `/subscribe` → инвойс в чате |

После успешной оплаты бот продлевает Premium в `subscribers.json`. История платежей — `payments.json` (для идемпотентности и refund).

> В BotFather для цифровых товаров provider token не нужен — только `currency=XTR`.

---

## Weekly Digest (Premium) — план

Еженедельная **графическая сводка** в **личный чат (DM)**. Только **Premium** — Free не получает.

### Расписание

| Параметр | Значение |
|----------|----------|
| Когда | **Каждое воскресенье** |
| Время | **12:00 дня** по **America/New_York** (NY / Eastern Time, EST/EDT автоматически) |
| Куда | DM каждому active Premium (`subscribers.json`) |
| Вручную | `/weekly` — та же карточка по запросу (только Premium) |

> Летом (EDT) ≈ 16:00 UTC; зимой (EST) ≈ 17:00 UTC — бот считает по `America/New_York`, не фиксированный UTC.

### Зачем

Не дублирует мгновенные алерты, а даёт **обзор за 7 дней**: кто купил/продал, по каким ценам, куда текут ETF.

### Содержание карточки

**Блок A — Компании** (Strategy + 5 treasury из `entities.json`):

| Колонка | Описание |
|---------|----------|
| Куплено за неделю (BTC) | сумма buy-сделок |
| **Ср. цена покупок за неделю ($)** | volume-weighted по журналу сделок |
| Продано за неделю (BTC) | сумма sell-сделок |
| **Ср. цена продаж за неделю ($)** | volume-weighted; для компаний — **оценка** по spot BTC в момент алерта* |
| Net BTC | приток/отток за неделю |
| Holdings сейчас | текущий баланс |
| Lifetime avg ($) | cost basis ÷ BTC (CoinGecko / strategy.com) |
| Unrealized PnL | из CoinGecko |

Дополнительно: **Whale of the week** (крупнейший buy/sell в BTC); строки без сделок — «—».

**Блок B — ETF** (IBIT, FBTC, GBTC, ARKB): net flow за неделю (BTC / $), лучший/худший день. Без «ср. цены покупки компании» — только потоки.

**Блок C — Рынок:** BTC начало vs конец недели (%); суммарный BTC у отслеживаемых китов.

**Caption:** период, «Premium digest», ссылки `/whales` · `/stats`.

\* Публичных данных о цене корпоративной **продажи** нет — только детект по падению баланса. В disclaimer: «sale prices estimated from spot at detection time». Strategy **покупки** — точная цена с strategy.com где доступна.

### Две фазы реализации

| Фаза | Что входит | Зависимости |
|------|------------|-------------|
| **v1 Snapshot** | Holdings, lifetime avg, PnL, net Δ BTC за неделю (baseline diff), ETF flows, BTC week change | День 19 (гейтинг + DM premium) |
| **v2 Trades** | Ср. цена **покупок и продаж за неделю** по каждой компании | Журнал `transactions.json` при каждом алерте ✅ |

### Технический план

```
День 19           →  кому слать (active Premium DM)
transactions.json →  запись при buy/sale в monitor_entities / main / monitor_etf
weekly_digest.py  →  агрегация 7 дней + generate_weekly_digest_card() в cards.py
Планировщик       →  вс 12:00 America/New_York → DM всем active Premium
/weekly           →  ручной запрос (Premium, вне расписания)
```

### Env (заготовки)

```bash
# WEEKLY_DIGEST_ENABLED=true
# WEEKLY_DIGEST_TIMEZONE=America/New_York
# WEEKLY_DIGEST_WEEKDAY=6              # 0=Mon … 6=Sun
# WEEKLY_DIGEST_HOUR=12                # 12:00 дня (полдень NY)
# WEEKLY_DIGEST_MINUTE=0
# TRANSACTIONS_FILE=transactions.json
```

### Ограничения (для `/disclaimer`)

- Ср. цена продаж компаний — оценка, не данные SEC.
- Неделя без сделок → «0 BTC · avg —».
- CoinGecko обновляется с задержкой; мелкие движения ниже порога `entities.json` не попадают.

---

## Следующие шаги (план)

- **День 17** ✅ — `subscribers.json` (user_id, plan, expires_at), `/mysub`, admin `/setsub`
- **День 18** ✅ — Telegram Stars (`/subscribe`, pre_checkout, successful_payment, `payments.json`)
- **День 19** ✅ — гейтинг + DM: admin instant; Premium instant+cards; Free Strategy text + delay
- **День 20** ✅ — `/subscribe`: описание Premium + inline-кнопка оплаты Stars
- **Digest v1** ✅ — Weekly Snapshot (PNG + `/weekly`, рассылка Premium вс 12:00 NY)
- **Digest v2** ✅ — `transactions.json`, buy/sell + avg price в weekly digest

---

## Env (заготовки)

```bash
# PREMIUM_PRICE_USD=7
# FREE_ALERT_DELAY_MINUTES=30
# SUBSCRIBERS_FILE=subscribers.json
# PREMIUM_STARS=350
# PREMIUM_BILLING_DAYS=30
# ENABLE_STARS_PAYMENTS=true
# PAYMENTS_FILE=payments.json
# WEEKLY_DIGEST_ENABLED=true
# WEEKLY_DIGEST_TIMEZONE=America/New_York
# WEEKLY_DIGEST_WEEKDAY=6
# WEEKLY_DIGEST_HOUR=12
# TRANSACTIONS_FILE=transactions.json
```

См. `.env.example`.
