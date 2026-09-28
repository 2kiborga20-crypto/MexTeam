import asyncio
import os
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("Укажите BOT_TOKEN")

ADMIN_ID = 123456789  # ЗАМЕНИ на свой ID из шага 2

conn = sqlite3.connect("bot.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


def init_db():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY,
        name TEXT,
        payout_type TEXT,
        payout_value TEXT
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_id INTEGER,
        fio TEXT,
        phone TEXT,
        bank TEXT,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_id INTEGER,
        amount TEXT,
        payout_type TEXT,
        payout_value TEXT,
        created_at TEXT
    );
    """)
    conn.commit()


class ReferralForm(StatesGroup):
    fio = State()
    phone = State()
    bank = State()


class PayoutForm(StatesGroup):
    sbp = State()
    crypto = State()


class WithdrawForm(StatesGroup):
    amount = State()


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Подать заявку", callback_data="new_referral")],
        [InlineKeyboardButton(text="💰 Заявка на вывод", callback_data="withdraw")],
        [InlineKeyboardButton(text="💳 Мои реквизиты", callback_data="payout_info")],
        [InlineKeyboardButton(text="📋 Мои заявки", callback_data="my_requests")],
    ])


def cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])


def payout_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 СБП", callback_data="payout:sbp")],
        [InlineKeyboardButton(text="🪙 CryptoBot", callback_data="payout:crypto")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])


def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В меню", callback_data="menu")]
    ])


def get_user(tg_id):
    return cur.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()


def requisites(row):
    if not row or not row["payout_type"]:
        return "❌ не заполнены"
    if row["payout_type"] == "sbp":
        return f"📱 СБП\n└ {row['payout_value']}"
    return f"🪙 CryptoBot\n└ {row['payout_value']}"


async def notify_admin(text):
    try:
        await bot.send_message(ADMIN_ID, text)
    except Exception:
        pass


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: Message):
    cur.execute(
        "INSERT OR IGNORE INTO users (tg_id, name) VALUES (?, ?)",
        (message.from_user.id, message.from_user.full_name)
    )
    conn.commit()
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Этот бот поможет подавать заявки на приведённых клиентов "
        "и запрашивать выплаты.\n\n"
        "Выберите действие 👇",
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "menu")
async def menu_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "🏠 Главное меню\n\nВыберите действие 👇",
        reply_markup=main_menu()
    )
    await call.answer()


@dp.callback_query(F.data == "cancel")
async def cancel_cb(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "🏠 Главное меню\n\nВыберите действие 👇",
        reply_markup=main_menu()
    )
    await call.answer("Отменено")


# --- Заявка на клиента ---

@dp.callback_query(F.data == "new_referral")
async def ref_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(ReferralForm.fio)
    await call.message.edit_text(
        "📝 Новая заявка на клиента\n━━━━━━━━━━━━━━━\n\n"
        "Шаг 1 из 3\n\nВведите ФИО приведённого клиента:",
        reply_markup=cancel_kb()
    )
    await call.answer()


@dp.message(ReferralForm.fio)
async def ref_fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text.strip())
    await state.set_state(ReferralForm.phone)
    await message.answer(
        "📝 Новая заявка на клиента\n━━━━━━━━━━━━━━━\n\n"
        "Шаг 2 из 3\n\nВведите номер телефона клиента:\n"
        "Например: +7 900 123-45-67",
        reply_markup=cancel_kb()
    )


@dp.message(ReferralForm.phone)
async def ref_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.text.strip())
    await state.set_state(ReferralForm.bank)
    await message.answer(
        "📝 Новая заявка на клиента\n━━━━━━━━━━━━━━━\n\n"
        "Шаг 3 из 3\n\nУкажите банк / отделение\n"
        "или отправьте «-», чтобы пропустить",
        reply_markup=cancel_kb()
    )


@dp.message(ReferralForm.bank)
async def ref_bank(message: Message, state: FSMContext):
    data = await state.get_data()
    bank = message.text.strip()
    if bank == "-":
        bank = ""
    cur.execute(
        "INSERT INTO referrals (worker_id, fio, phone, bank, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (message.from_user.id, data["fio"], data["phone"], bank,
         datetime.now().strftime("%d.%m.%Y %H:%M"))
    )
    conn.commit()
    rid = cur.lastrowid
    await state.clear()

    await message.answer(
        f"✅ Заявка #{rid} отправлена!\n━━━━━━━━━━━━━━━\n\n"
        f"👤 ФИО: {data['fio']}\n"
        f"📱 Телефон: {data['phone']}\n"
        f"🏦 Банк: {bank or '—'}\n\n"
        f"Статус: на проверке",
        reply_markup=back_kb()
    )
    await notify_admin(
        f"📥 Новая заявка #{rid}\n\n"
        f"👤 {data['fio']}\n"
        f"📱 {data['phone']}\n"
        f"🏦 {bank or '—'}\n"
        f"👨‍💼 {message.from_user.full_name} (id: {message.from_user.id})"
    )


# --- Реквизиты ---

@dp.callback_query(F.data == "payout_info")
async def payout_info(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user = get_user(call.from_user.id)
    if user and user["payout_type"]:
        text = (
            "💳 Мои реквизиты\n━━━━━━━━━━━━━━━\n\n"
            f"{requisites(user)}\n\nХотите изменить?"
        )
    else:
        text = (
            "💳 Реквизиты для выплат\n━━━━━━━━━━━━━━━\n\n"
            "❌ У вас ещё не заполнены реквизиты.\n\n"
            "Выберите способ получения выплаты 👇"
        )
    await call.message.edit_text(text, reply_markup=payout_kb())
    await call.answer()


@dp.callback_query(F.data.startswith("payout:"))
async def payout_choose(call: CallbackQuery, state: FSMContext):
    method = call.data.split(":")[1]
    if method == "sbp":
        await state.set_state(PayoutForm.sbp)
        await call.message.edit_text(
            "📱 СБП\n━━━━━━━━━━━━━━━\n\n"
            "Введите номер телефона, привязанный к СБП:\n"
            "Например: +7 900 123-45-67",
            reply_markup=cancel_kb()
        )
    else:
        await state.set_state(PayoutForm.crypto)
        await call.message.edit_text(
            "🪙 CryptoBot\n━━━━━━━━━━━━━━━\n\n"
            "Введите ваш @username в Telegram или адрес кошелька USDT:\n"
            "Например: @ivanov или TRC20-адрес",
            reply_markup=cancel_kb()
        )
    await call.answer()


@dp.message(PayoutForm.sbp)
async def save_sbp(message: Message, state: FSMContext):
    value = message.text.strip()
    cur.execute(
        "UPDATE users SET payout_type = 'sbp', payout_value = ? WHERE tg_id = ?",
        (value, message.from_user.id)
    )
    conn.commit()
    await state.clear()
    await message.answer(
        f"✅ Реквизиты сохранены\n━━━━━━━━━━━━━━━\n\n📱 СБП\n└ {value}",
        reply_markup=back_kb()
    )


@dp.message(PayoutForm.crypto)
async def save_crypto(message: Message, state: FSMContext):
    value = message.text.strip()
    cur.execute(
        "UPDATE users SET payout_type = 'crypto', payout_value = ? WHERE tg_id = ?",
        (value, message.from_user.id)
    )
    conn.commit()
    await state.clear()
    await message.answer(
        f"✅ Реквизиты сохранены\n━━━━━━━━━━━━━━━\n\n🪙 CryptoBot\n└ {value}",
        reply_markup=back_kb()
    )


# --- Заявка на вывод ---

@dp.callback_query(F.data == "withdraw")
async def withdraw_start(call: CallbackQuery, state: FSMContext):
    await state.clear()
    user = get_user(call.from_user.id)
    if not user or not user["payout_type"]:
        await call.message.edit_text(
            "⚠️ Реквизиты не заполнены\n━━━━━━━━━━━━━━━\n\n"
            "Чтобы подать заявку на вывод, сначала заполните данные для выплаты.\n\n"
            "Выберите способ 👇",
            reply_markup=payout_kb()
        )
        await call.answer()
        return
    await state.set_state(WithdrawForm.amount)
    await call.message.edit_text(
        "💰 Заявка на вывод\n━━━━━━━━━━━━━━━\n\n"
        f"Ваши реквизиты:\n{requisites(user)}\n\n"
        "Укажите сумму к выводу:\n"
        "Например: 5000 ₽ или 50 USDT",
        reply_markup=cancel_kb()
    )
    await call.answer()


@dp.message(WithdrawForm.amount)
async def withdraw_amount(message: Message, state: FSMContext):
    amount = message.text.strip()
    user = get_user(message.from_user.id)
    cur.execute(
        "INSERT INTO withdrawals (worker_id, amount, payout_type, payout_value, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (message.from_user.id, amount, user["payout_type"], user["payout_value"],
         datetime.now().strftime("%d.%m.%Y %H:%M"))
    )
    conn.commit()
    wid = cur.lastrowid
    await state.clear()

    await message.answer(
        f"✅ Заявка на вывод #{wid} отправлена!\n━━━━━━━━━━━━━━━\n\n"
        f"💵 Сумма: {amount}\n{requisites(user)}\n\n"
        f"Статус: на обработке",
        reply_markup=back_kb()
    )
    await notify_admin(
        f"💸 Заявка на вывод #{wid}\n\n"
        f"👨‍💼 {message.from_user.full_name} (id: {message.from_user.id})\n"
        f"💵 Сумма: {amount}\n{requisites(user)}"
    )


# --- Мои заявки ---

@dp.callback_query(F.data == "my_requests")
async def my_requests(call: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = call.from_user.id
    refs = cur.execute(
        "SELECT * FROM referrals WHERE worker_id = ? ORDER BY id DESC LIMIT 5",
        (uid,)
    ).fetchall()
    wds = cur.execute(
        "SELECT * FROM withdrawals WHERE worker_id = ? ORDER BY id DESC LIMIT 5",
        (uid,)
    ).fetchall()

    parts = ["📋 Мои заявки\n━━━━━━━━━━━━━━━\n", "Клиенты:"]
    if refs:
        for r in refs:
            parts.append(
                f"#{r['id']} • {r['fio']}\n"
                f"└ 📱 {r['phone']} • 🏦 {r['bank'] or '—'}\n"
                f"└ 🕓 {r['created_at']}"
            )
    else:
        parts.append("пока нет")

    parts.append("\nВыводы:")
    if wds:
        for w in wds:
            parts.append(
                f"#{w['id']} • 💵 {w['amount']}\n"
                f"└ {w['payout_type'].upper()} • {w['payout_value']}\n"
                f"└ 🕓 {w['created_at']}"
            )
    else:
        parts.append("пока нет")

    await call.message.edit_text("\n".join(parts), reply_markup=back_kb())
    await call.answer()


async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
