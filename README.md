# Steam Top-Up Bot (Telegram)

Минималистичный одноэкранный Telegram-бот для пополнения Steam через PlayWallet API и оплату в YooKassa.

## Что умеет
- Single-account и multi-account сценарии в одном экране (через редактирование одного сообщения).
- Ввод Steam login с предупреждением, что логин ≠ никнейм.
- Быстрый выбор суммы (пресеты + кастом).
- Мгновенный расчет:
  - стоимость провайдера (PlayWallet quote),
  - merchant markup (по умолчанию 5%),
  - итог к оплате,
  - оценка зачисления в USD.
- Создание платежа YooKassa.
- Проверка оплаты и последующее создание/отслеживание заказов в PlayWallet.

## Как запустить на твоем компьютере

### 1) Установи зависимости
- Python 3.11+ (рекомендовано)
- `pip`

Проверь:
```bash
python --version
pip --version
```

### 2) Склонируй проект и перейди в папку
```bash
git clone <URL_твоего_репозитория>
cd TitanTopUP
```

### 3) Создай и активируй venv

**Linux / macOS**
```bash
python -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell)**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 4) Установи Python-пакеты
```bash
pip install -r requirements.txt
```

### 5) Настрой переменные окружения
Есть готовый пример: `.env.example`.

Скопируй его в `.env` и заполни своими значениями:
```bash
cp .env.example .env
```

Минимально обязательно:
- `BOT_TOKEN`

Опционально (для реальных платежей и реальных пополнений):
- `PLAYWALLET_API_KEY`
- `YOOKASSA_SHOP_ID`
- `YOOKASSA_SECRET_KEY`

> Если PlayWallet/YooKassa ключи не заданы, бот запускается в mock-режиме (удобно для локальной проверки UX).

### 6) Экспортируй переменные из `.env`

**Linux / macOS**
```bash
set -a
source .env
set +a
```

**Windows (PowerShell)**
```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
  $name, $value = $_ -split '=', 2
  [System.Environment]::SetEnvironmentVariable($name, $value, 'Process')
}
```

### 7) Запусти бота
```bash
python bot.py
```

Если всё ок — открой Telegram, найди своего бота и нажми `/start`.

## Быстрый запуск одной командой (Linux / macOS)
```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && set -a && source .env && set +a && python bot.py
```

## Переменные окружения
- `BOT_TOKEN` — токен Telegram-бота.
- `MERCHANT_MARKUP_PERCENT` — наценка мерчанта, по умолчанию `5`.
- `PLAYWALLET_API_KEY`, `PLAYWALLET_BASE_URL`.
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_BASE_URL`, `YOOKASSA_RETURN_URL`.

## UX-концепция single-screen
- Бот закрепляет один основной экран и обновляет его inline-кнопками.
- Все шаги (логин → сумма → quote → оплата → финальный статус) проходят без “ветвления” интерфейса.
