import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
PLAYWALLET_API_KEY = os.getenv("PLAYWALLET_API_KEY", "")
PLAYWALLET_BASE_URL = os.getenv("PLAYWALLET_BASE_URL", "https://api.playwallet.example")
YOOKASSA_SHOP_ID = os.getenv("YOOKASSA_SHOP_ID", "")
YOOKASSA_SECRET_KEY = os.getenv("YOOKASSA_SECRET_KEY", "")
YOOKASSA_RETURN_URL = os.getenv("YOOKASSA_RETURN_URL", "https://t.me")
YOOKASSA_BASE_URL = os.getenv("YOOKASSA_BASE_URL", "https://api.yookassa.ru/v3")
MERCHANT_MARKUP_PERCENT = Decimal(os.getenv("MERCHANT_MARKUP_PERCENT", "5"))

PRESET_AMOUNTS = [200, 500, 1000, 2000]


@dataclass
class AccountTopUp:
    login: str
    amount_rub: Optional[Decimal] = None
    quote_payment_rub: Optional[Decimal] = None
    quote_credit_usd: Optional[Decimal] = None


@dataclass
class SessionState:
    message_id: Optional[int] = None
    accounts: List[AccountTopUp] = field(default_factory=list)
    pending_login: bool = True
    pending_custom_amount_for_login: Optional[str] = None
    payment_id: Optional[str] = None
    payment_url: Optional[str] = None


SESSIONS: Dict[int, SessionState] = {}


class PlayWalletClient:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def get_quote(self, steam_login: str, amount_rub: Decimal) -> tuple[Decimal, Decimal]:
        if not PLAYWALLET_API_KEY:
            provider_cost = amount_rub * Decimal("0.92")
            credited_usd = amount_rub / Decimal("95")
            return provider_cost.quantize(Decimal("0.01")), credited_usd.quantize(Decimal("0.01"))

        payload = {"steam_login": steam_login, "amount_rub": float(amount_rub)}
        headers = {"Authorization": f"Bearer {PLAYWALLET_API_KEY}"}
        async with self.session.post(f"{PLAYWALLET_BASE_URL}/quotes/steam", json=payload, headers=headers) as resp:
            data = await resp.json()
            provider_cost = Decimal(str(data["provider_cost_rub"]))
            credited_usd = Decimal(str(data["estimated_credit_usd"]))
            return provider_cost, credited_usd

    async def create_topup_order(self, steam_login: str, amount_rub: Decimal, external_id: str) -> str:
        if not PLAYWALLET_API_KEY:
            await asyncio.sleep(0.2)
            return f"mock-order-{steam_login}-{external_id}"

        payload = {
            "steam_login": steam_login,
            "amount_rub": float(amount_rub),
            "external_id": external_id,
        }
        headers = {"Authorization": f"Bearer {PLAYWALLET_API_KEY}"}
        async with self.session.post(f"{PLAYWALLET_BASE_URL}/orders/steam", json=payload, headers=headers) as resp:
            data = await resp.json()
            return data["order_id"]

    async def wait_for_order_completion(self, order_id: str, timeout_seconds: int = 120) -> str:
        if not PLAYWALLET_API_KEY:
            await asyncio.sleep(1)
            return "completed"

        headers = {"Authorization": f"Bearer {PLAYWALLET_API_KEY}"}
        elapsed = 0
        while elapsed < timeout_seconds:
            async with self.session.get(f"{PLAYWALLET_BASE_URL}/orders/{order_id}", headers=headers) as resp:
                data = await resp.json()
                status = data.get("status", "pending")
                if status in {"completed", "failed", "cancelled"}:
                    return status
            await asyncio.sleep(4)
            elapsed += 4
        return "timeout"


class YooKassaClient:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    async def create_payment(self, amount_rub: Decimal, description: str) -> tuple[str, str]:
        if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
            payment_id = f"mock-payment-{uuid.uuid4().hex[:10]}"
            return payment_id, f"https://t.me?start={payment_id}"

        headers = {
            "Idempotence-Key": uuid.uuid4().hex,
            "Content-Type": "application/json",
        }
        auth = aiohttp.BasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
        payload = {
            "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": YOOKASSA_RETURN_URL},
            "description": description,
        }
        async with self.session.post(f"{YOOKASSA_BASE_URL}/payments", headers=headers, auth=auth, json=payload) as resp:
            data = await resp.json()
            return data["id"], data["confirmation"]["confirmation_url"]

    async def is_paid(self, payment_id: str) -> bool:
        if not YOOKASSA_SHOP_ID or not YOOKASSA_SECRET_KEY:
            return True

        auth = aiohttp.BasicAuth(YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY)
        async with self.session.get(f"{YOOKASSA_BASE_URL}/payments/{payment_id}", auth=auth) as resp:
            data = await resp.json()
            return data.get("status") == "succeeded"


def format_money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_session(chat_id: int) -> SessionState:
    return SESSIONS.setdefault(chat_id, SessionState())


def build_screen(state: SessionState) -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        "💳 *Steam Top-Up Bot*",
        "⚠️ Логин Steam — это не никнейм профиля.",
        "",
    ]

    if not state.accounts:
        lines.append("1) Отправьте логин Steam одним сообщением.")
    else:
        lines.append("Текущие аккаунты:")
        for idx, account in enumerate(state.accounts, start=1):
            quote = ""
            if account.quote_payment_rub and account.quote_credit_usd:
                quote = f" — к оплате {format_money(account.quote_payment_rub)} RUB (~{format_money(account.quote_credit_usd)} USD)"
            lines.append(f"{idx}. `{account.login}` / сумма: {account.amount_rub or '-'} RUB{quote}")

    lines.append("\n2) Выберите сумму пополнения для текущего аккаунта.")

    rows = [[InlineKeyboardButton(text=f"{a} ₽", callback_data=f"amount:{a}") for a in PRESET_AMOUNTS[:2]],
            [InlineKeyboardButton(text=f"{a} ₽", callback_data=f"amount:{a}") for a in PRESET_AMOUNTS[2:]],
            [InlineKeyboardButton(text="✏️ Своя сумма", callback_data="amount:custom")],
            [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="account:add")],
            [InlineKeyboardButton(text="💸 Оплатить", callback_data="checkout")]]

    if state.payment_url:
        rows.append([InlineKeyboardButton(text="Открыть оплату YooKassa", url=state.payment_url)])
        rows.append([InlineKeyboardButton(text="✅ Я оплатил", callback_data="payment:check")])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def redraw(bot: Bot, chat_id: int):
    state = get_session(chat_id)
    text, kb = build_screen(state)
    if state.message_id:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=state.message_id,
            text=text,
            reply_markup=kb,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown", disable_web_page_preview=True)
        state.message_id = msg.message_id


async def calculate_quote(playwallet: PlayWalletClient, account: AccountTopUp):
    provider_cost, credit = await playwallet.get_quote(account.login, account.amount_rub or Decimal("0"))
    quote_payment = provider_cost * (Decimal("1") + MERCHANT_MARKUP_PERCENT / Decimal("100"))
    account.quote_payment_rub = quote_payment.quantize(Decimal("0.01"))
    account.quote_credit_usd = credit


async def handle_checkout(bot: Bot, cq: CallbackQuery, yk: YooKassaClient):
    state = get_session(cq.message.chat.id)
    ready = [a for a in state.accounts if a.quote_payment_rub]
    if not ready:
        await cq.answer("Сначала добавьте аккаунт и сумму", show_alert=True)
        return

    total = sum((a.quote_payment_rub for a in ready), Decimal("0"))
    description = f"Steam top-up: {', '.join(a.login for a in ready)}"
    payment_id, payment_url = await yk.create_payment(total, description)
    state.payment_id = payment_id
    state.payment_url = payment_url
    await redraw(bot, cq.message.chat.id)
    await cq.answer("Счёт создан")


async def process_topups(playwallet: PlayWalletClient, accounts: List[AccountTopUp]) -> list[str]:
    results = []
    for acc in accounts:
        ext = uuid.uuid4().hex[:12]
        oid = await playwallet.create_topup_order(acc.login, acc.amount_rub or Decimal("0"), ext)
        status = await playwallet.wait_for_order_completion(oid)
        results.append(f"{acc.login}: {status}")
    return results


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN env var")

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()

    session = aiohttp.ClientSession()
    playwallet = PlayWalletClient(session)
    yk = YooKassaClient(session)

    @dp.message(CommandStart())
    async def start(message: Message):
        SESSIONS[message.chat.id] = SessionState()
        await redraw(bot, message.chat.id)

    @dp.message(F.text)
    async def text_router(message: Message):
        state = get_session(message.chat.id)
        text = message.text.strip()

        if state.pending_custom_amount_for_login:
            try:
                amount = Decimal(text)
                if amount <= 0:
                    raise ValueError
            except Exception:
                await message.answer("Введите корректную сумму, например 750")
                return
            for a in state.accounts:
                if a.login == state.pending_custom_amount_for_login:
                    a.amount_rub = amount
                    await calculate_quote(playwallet, a)
            state.pending_custom_amount_for_login = None
            await redraw(bot, message.chat.id)
            return

        # Treat as steam login
        state.accounts.append(AccountTopUp(login=text))
        state.pending_login = False
        await redraw(bot, message.chat.id)

    @dp.callback_query(F.data.startswith("amount:"))
    async def amount_chosen(cq: CallbackQuery):
        state = get_session(cq.message.chat.id)
        if not state.accounts:
            await cq.answer("Сначала отправьте Steam логин", show_alert=True)
            return
        current = state.accounts[-1]
        _, raw_amount = cq.data.split(":", 1)
        if raw_amount == "custom":
            state.pending_custom_amount_for_login = current.login
            await cq.answer("Отправьте сумму одним сообщением")
            return

        current.amount_rub = Decimal(raw_amount)
        await calculate_quote(playwallet, current)
        await redraw(bot, cq.message.chat.id)
        await cq.answer("Сумма обновлена")

    @dp.callback_query(F.data == "account:add")
    async def add_account(cq: CallbackQuery):
        state = get_session(cq.message.chat.id)
        state.pending_login = True
        await cq.answer("Отправьте логин нового Steam аккаунта")

    @dp.callback_query(F.data == "checkout")
    async def checkout(cq: CallbackQuery):
        await handle_checkout(bot, cq, yk)

    @dp.callback_query(F.data == "payment:check")
    async def payment_check(cq: CallbackQuery):
        state = get_session(cq.message.chat.id)
        if not state.payment_id:
            await cq.answer("Сначала создайте счёт", show_alert=True)
            return

        paid = await yk.is_paid(state.payment_id)
        if not paid:
            await cq.answer("Оплата пока не найдена", show_alert=True)
            return

        await cq.answer("Оплата подтверждена, пополняем...")
        results = await process_topups(playwallet, state.accounts)
        state.payment_url = None
        state.payment_id = None
        await redraw(bot, cq.message.chat.id)
        await bot.send_message(cq.message.chat.id, "\n".join(["✅ Результат пополнения:", *results]))

    try:
        await dp.start_polling(bot)
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
