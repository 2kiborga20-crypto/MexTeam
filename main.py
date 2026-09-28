import asyncio
import os
import re
import sqlite3
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)

BOT_TOKEN = "8805214954:AAHEkkq4TEAuu457JtNq1eO0CE9cw0gqxk0"
if not BOT_TOKEN:
    raise RuntimeError("Укажите BOT_TOKEN")

ADMIN_ID = 7891556528  # ваш ID
REWARD = 700           # сколько рублей за одну одобренную заявку

conn = sqlite3.connect("bot.db", check_same_thread=False)
conn.row_factory = sqlite3.Row
cur = conn.cursor()


def init_db():
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY,
        name TEXT,
        username TEXT,
        payout_type TEXT,
        payout_value TEXT
    );
    CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_id INTEGER,
        fio TEXT,
        phone TEXT,
        bank TEXT,
        status TEXT DEFAULT 'new',
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS withdrawals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        worker_id INTEGER,
        amount TEXT,
        amount_num INTEGER DEFAULT 0,
        payout_type TEXT,
        payout_value TEXT,
        status TEXT DEFAULT 'new',
        created_at TEXT
    );
    """)
    conn.commit()

    # добавляем колонки для старых баз
    for stmt in (
        "ALTER TABLE users ADD COLUMN username TEXT",
        "ALTER TABLE withdrawals ADD COLUMN amount_num INTEGER DEFAULT 0",
    ):
        try:
            cur.execute(stmt)
            conn.commit()
        except sqlite3.OperationalError:
            pass


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
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="💳 Реквизиты", callback_data="payout_info")],
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


def decision_kb(kind, item_id, worker_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Подтвердить",
                callback_data=f"ok:{kind}:{item_id}:{worker_id}"
            ),
            InlineKeyboardButton(
                text="❌ Отказать",
                callback_data=f"no:{kind}:{item_id}:{worker_id}"
            ),
        ]
    ])


def get_user(tg_id):
    return cur.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,)).fetchone()


def requisites(row):
    if not row or not row["payout_type"]:
        return "❌ не заполнены"
    if row["payout_type"] == "sbp":
        return f"📱 СБП\n└ {row['payout_value']}"
    return f"🪙 CryptoBot\n└ {row['payout_value']}"


def get_stats(uid):
    """Возвращает (заработано, выведено, в обработке, баланс)"""
    approved_refs = cur.execute(
        "SELECT COUNT(*) c FROM referrals WHERE worker_id = ? AND status = 'approved'",
        (uid,)
    ).fetchone()["c"]
    earned = approved_refs * REWARD

    paid = cur.execute(
        "SELECT COALESCE(SUM(amount_num), 0) s FROM withdrawals "
        "WHERE worker_id = ? AND status = 'approved'",
        (uid,)
    ).fetchone()["s"]

    pending = cur.execute(
        "SELECT COALESCE(SUM(amount_num), 0) s FROM withdrawals "
        "WHERE worker_id = ? AND status = 'new'",
        (uid,)
    ).fetchone()["s"]

    balance = earned - paid - pending
    return earned, paid, pending, balance


def parse_amount(text: str) -> int:
    """Вытаскивает число из строки типа '5000 ₽' или '50 USDT'."""
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else 0


bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


@dp.message(Command("start"))
async def start(message: Message):
    cur.execute(
        "INSERT OR IGNORE INTO users (tg_id, name, username) VALUES (?, ?, ?)",
        (message.from_user.id, message.from_user.full_name, message.from_user.username)
    )
    cur.execute(
        "UPDATE users SET name = ?, username = ? WHERE tg_id = ?",
        (message.from_user.full_name, message.from_user.username, message.from_user.id)
    )
    conn.commit()
    await message.answer(
        "👋 Добро пожаловать!\n\n"
        "Этот бот поможет подавать заявки на приведённых клиентов "
        "и запрашивать выплаты.\n\n"
        f"💰 За каждого одобренного клиента: <b>{REWARD} ₽</b>\n\n"
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


# --- Профиль ---

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery, state: FSMContext):
    await state.clear()
    uid = call.from_user.id
    user = get_user(uid)
    earned, paid, pending, balance = get_stats(uid)

    nick = (user["username"] and f"@{user['username']}") or user["name"] or "—"

    approved_count = cur.execute(
        "SELECT COUNT(*) c FROM referrals WHERE worker_id = ? AND status = 'approved'",
        (uid,)
    ).fetchone()["c"]
    total_count = cur.execute(
        "SELECT COUNT(*) c FROM referrals WHERE worker_id = ?",
        (uid,)
    ).fetchone()["c"]

    text = (
        "👤 <b>Профиль</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"🆔 Ник: <b>{nick}</b>\n"
        f"💰 За клиента: <b>{REWARD} ₽</b>\n\n"
        f"📊 Всего заявок: <b>{total_count}</b>\n"
        f"✅ Одобрено: <b>{approved_count}</b>\n\n"
        "━━━━━━━━━━━━━━━\n"
        f"💵 Заработано: <b>{earned} ₽</b>\n"
        f"📤 Выведено: <b>{paid} ₽</b>\n"
        f"⏳ В обработке: <b>{pending} ₽</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"🟢 Доступно к выводу: <b>{balance} ₽</b>"
    )

    await call.message.edit_text(text, reply_markup=main_menu())
    await call.answer()


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
        f"Статус: на проверке\n"
        f"💰 Вознаграждение: {REWARD} ₽ после одобрения",
        reply_markup=back_kb()
    )

    await bot.send_message(
        ADMIN_ID,
        f"📥 Новая заявка #{rid}\n\n"
        f"👤 {data['fio']}\n"
        f"📱 {data['phone']}\n"
        f"🏦 {bank or '—'}\n"
        f"👨‍💼 {message.from_user.full_name} (id: {message.from_user.id})",
        reply_markup=decision_kb("ref", rid, message.from_user.id)
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

    earned, paid, pending, balance = get_stats(call.from_user.id)

    if balance <= 0:
        await call.message.edit_text(
            "💰 Заявка на вывод\n━━━━━━━━━━━━━━━\n\n"
            f"🟢 Доступно к выводу: <b>{balance} ₽</b>\n\n"
            "Пока нечего выводить. Приведите клиентов и дождитесь одобрения заявок.",
            reply_markup=main_menu()
        )
        await call.answer()
        return

    await state.set_state(WithdrawForm.amount)
    await call.message.edit_text(
        "💰 Заявка на вывод\n━━━━━━━━━━━━━━━\n\n"
        f"Ваши реквизиты:\n{requisites(user)}\n\n"
        f"🟢 Доступно к выводу: <b>{balance} ₽</b>\n\n"
        "Укажите сумму к выводу (в рублях):\n"
        f"Например: {balance}",
        reply_markup=cancel_kb()
    )
    await call.answer()


@dp.message(WithdrawForm.amount)
async def withdraw_amount(message: Message, state: FSMContext):
    text = message.text.strip()
    amount_num = parse_amount(text)
    user = get_user(message.from_user.id)
    earned, paid, pending, balance = get_stats(message.from_user.id)

    if amount_num <= 0:
        return await message.answer(
            "❌ Не понял сумму. Введите число, например: 700",
            reply_markup=cancel_kb()
        )

    if amount_num > balance:
        return await message.answer(
            f"❌ Сумма больше доступного.\n"
            f"🟢 Доступно: <b>{balance} ₽</b>\n\n"
            "Введите сумму меньше или равную балансу:",
            reply_markup=cancel_kb()
        )

    cur.execute(
        "INSERT INTO withdrawals (worker_id, amount, amount_num, payout_type, "
        "payout_value, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (message.from_user.id, f"{amount_num} ₽", amount_num,
         user["payout_type"], user["payout_value"],
         datetime.now().strftime("%d.%m.%Y %H:%M"))
    )
    conn.commit()
    wid = cur.lastrowid
    await state.clear()

    await message.answer(
        f"✅ Заявка на вывод #{wid} отправлена!\n━━━━━━━━━━━━━━━\n\n"
        f"💵 Сумма: <b>{amount_num} ₽</b>\n{requisites(user)}\n\n"
        f"Статус: на обработке",
        reply_markup=back_kb()
    )

    await bot.send_message(
        ADMIN_ID,
        f"💸 Заявка на вывод #{wid}\n\n"
        f"👨‍💼 {message.from_user.full_name} (id: {message.from_user.id})\n"
        f"💵 Сумма: {amount_num} ₽\n{requisites(user)}",
        reply_markup=decision_kb("wd", wid, message.from_user.id)
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

    status_names = {
        "new": "🕓 на проверке",
        "approved": "✅ одобрена",
        "rejected": "❌ отклонена",
    }

    parts = ["📋 Мои заявки\n━━━━━━━━━━━━━━━\n", "Клиенты:"]
    if refs:
        for r in refs:
            parts.append(
                f"#{r['id']} • {r['fio']}\n"
                f"└ 📱 {r['phone']} • 🏦 {r['bank'] or '—'}\n"
                f"└ {status_names.get(r['status'], '🕓 на проверке')}"
            )
    else:
        parts.append("пока нет")

    parts.append("\nВыводы:")
    if wds:
        for w in wds:
            parts.append(
                f"#{w['id']} • 💵 {w['amount']}\n"
                f"└ {w['payout_type'].upper()} • {w['payout_value']}\n"
                f"└ {status_names.get(w['status'], '🕓 на проверке')}"
            )
    else:
        parts.append("пока нет")

    await call.message.edit_text("\n".join(parts), reply_markup=main_menu())
    await call.answer()


# --- Решение админа по заявке ---

@dp.callback_query(F.data.startswith(("ok:", "no:")))
async def admin_decision(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("Нет доступа", show_alert=True)

    action, kind, item_id, worker_id = call.data.split(":")
    item_id = int(item_id)
    worker_id = int(worker_id)
    approved = action == "ok"

    table = "referrals" if kind == "ref" else "withdrawals"
    status = "approved" if approved else "rejected"

    cur.execute(f"UPDATE {table} SET status = ? WHERE id = ?", (status, item_id))
    conn.commit()

    if kind == "ref":
        if approved:
            worker_text = (
                f"✅ Заявка #{item_id} одобрена!\n\n"
                f"💰 Начислено: +{REWARD} ₽\n"
                f"Проверить баланс: 👤 Профиль"
            )
        else:
            worker_text = (
                f"❌ Заявка #{item_id} отклонена.\n\n"
                f"Если считаете это ошибкой — свяжитесь с администратором."
            )
    else:
        if approved:
            worker_text = (
                f"✅ Заявка на вывод #{item_id} одобрена!\n\n"
                f"💵 Выплата произведена. Проверить баланс: 👤 Профиль"
            )
        else:
            worker_text = (
                f"❌ Заявка на вывод #{item_id} отклонена.\n\n"
                f"Свяжитесь с администратором для уточнения."
            )

    try:
        await bot.send_message(worker_id, worker_text)
    except Exception:
        pass

    new_text = (call.message.html_text or call.message.text) + (
        "\n\n✅ <b>ОДОБРЕНО</b>" if approved else "\n\n❌ <b>ОТКЛОНЕНО</b>"
    )
    try:
        await call.message.edit_text(new_text, reply_markup=None, parse_mode="HTML")
    except Exception:
        await call.message.edit_reply_markup(reply_markup=None)

    await call.answer("Готово")


async def main():
    init_db()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
