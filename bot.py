import asyncio
import logging
import sqlite3
import os
import random
import csv
import io
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramConflictError
from aiohttp import web, ClientSession

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = "7799961207:AAEPNytcZZ8iseximsxmSDD6j-IrSW25hD8"
# Замените на ваш file_id после получения его от бота
MAIN_MENU_PHOTO = "AgACAgIAAxkBAAEY..." 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [SYSTEM] - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Списки категорий
EXPENSE_CATEGORIES = ["🍎 Продукты", "☕️ Кафе/Рестораны", "🚗 Транспорт", "🏠 Жилье/ЖКХ", "📱 Связь", "🎁 Подарки", "💊 Здоровье", "👕 Одежда", "🎮 Досуг", "🛒 Прочее"]
INCOME_CATEGORIES = ["💰 Зарплата", "💵 Аванс", "📈 Инвестиции", "💳 Фриланс", "➕ Другое"]

# Состояния FSM
class FinanceState(StatesGroup):
    choosing_type = State()
    choosing_category = State()
    entering_amount = State()
    entering_comment = State()
    setting_limit = State()
    adding_subscription = State()

DB_PATH = 'finance_manager.db'

# --- ИНИЦИАЛИЗАЦИЯ БД ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Транзакции
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, category TEXT, 
                       amount REAL, date TEXT, month_year TEXT, comment TEXT)''')
    # Лимиты
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_limits 
                      (user_id INTEGER PRIMARY KEY, monthly_limit REAL)''')
    # Подписки
    cursor.execute('''CREATE TABLE IF NOT EXISTS subscriptions 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, amount REAL, day INTEGER)''')
    conn.commit()
    conn.close()

init_db()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_current_month():
    return datetime.now().strftime("%m.%Y")

async def get_exchange_rates():
    """Запрос курсов валют ЦБ РФ"""
    try:
        async with ClientSession() as session:
            async with session.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=5) as resp:
                data = await resp.json()
                usd = data['Valute']['USD']['Value']
                eur = data['Valute']['EUR']['Value']
                return f"💵 USD: {usd:.2f}₽ | 💶 EUR: {eur:.2f}₽"
    except Exception as e:
        logger.error(f"Ошибка курсов: {e}")
        return "🏦 Курсы ЦБ временно недоступны"

def generate_progress_bar(percent, length=10):
    percent = max(0, min(100, percent))
    filled = int(length * percent / 100)
    return '🔵' * filled + '⚪' * (length - filled)

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    rates = await get_exchange_rates()
    
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT monthly_limit FROM user_limits WHERE user_id=?", (uid,))
        res_limit = c.fetchone()
        user_limit = res_limit[0] if res_limit else 0

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="➕ Операция", callback_data="add_transaction"),
                types.InlineKeyboardButton(text="📅 Подписки", callback_data="manage_subs"))
    builder.row(types.InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats"),
                types.InlineKeyboardButton(text="🎯 Лимит", callback_data="set_limit_start"))
    builder.row(types.InlineKeyboardButton(text="🔍 Детализация", callback_data="show_misc_details"),
                types.InlineKeyboardButton(text="📜 Архив", callback_data="show_archive"))
    builder.row(types.InlineKeyboardButton(text="📂 Экспорт CSV", callback_data="export_csv"),
                types.InlineKeyboardButton(text="🗑 Удалить", callback_data="manage_delete"))
    builder.row(types.InlineKeyboardButton(text="🕹 Мини-игра", callback_data="play_game"))
    
    caption = (
        f"🥷🏿 <b>Finance Pro [Ultimate v3.1]</b>\n\n"
        f"📈 <b>Курсы:</b> {rates}\n"
        f"🎯 <b>Лимит:</b> {user_limit if user_limit > 0 else 'не задан'}₽\n"
        f"📅 <b>Месяц:</b> {get_current_month()}\n\n"
        "Выберите действие в меню:"
    )

    try:
        await message.answer_photo(photo=MAIN_MENU_PHOTO, caption=caption, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        await message.answer(caption, reply_markup=builder.as_markup(), parse_mode="HTML")

# --- ЛОГИКА ДОБАВЛЕНИЯ ТРАНЗАКЦИЙ ---
@dp.callback_query(F.data == "add_transaction")
async def add_tx_start(cb: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="📉 Расход", callback_data="type_expense"), 
                types.InlineKeyboardButton(text="📈 Доход", callback_data="type_income"))
    await state.set_state(FinanceState.choosing_type)
    await cb.message.answer("Выберите тип операции:", reply_markup=builder.as_markup())
    await cb.answer()

@dp.callback_query(FinanceState.choosing_type, F.data.startswith("type_"))
async def add_tx_type(cb: types.CallbackQuery, state: FSMContext):
    t_type = "expense" if cb.data == "type_expense" else "income"
    await state.update_data(transaction_type=t_type)
    cats = EXPENSE_CATEGORIES if t_type == "expense" else INCOME_CATEGORIES
    builder = InlineKeyboardBuilder()
    for cat in cats: builder.add(types.InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}"))
    builder.adjust(2).row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="add_transaction"))
    await state.set_state(FinanceState.choosing_category)
    await cb.message.edit_text("Выберите категорию:", reply_markup=builder.as_markup())

@dp.callback_query(FinanceState.choosing_category, F.data.startswith("cat_"))
async def add_tx_cat(cb: types.CallbackQuery, state: FSMContext):
    category = cb.data.split("_")[1]
    await state.update_data(category=category)
    await state.set_state(FinanceState.entering_amount)
    await cb.message.edit_text(f"Выбрано: <b>{category}</b>\nВведите сумму (числом):", parse_mode="HTML")

@dp.message(FinanceState.entering_amount)
async def add_tx_amt(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
        await state.update_data(amount=amount)
        
        data = await state.get_data()
        # Если категория Прочее/Другое или сумма большая - просим коммент
        if any(x in data['category'] for x in ["Прочее", "Другое"]) or amount > 5000:
            await state.set_state(FinanceState.entering_comment)
            await message.answer("📝 Введите краткое описание:")
        else:
            await save_transaction(message, state)
    except:
        await message.answer("⚠️ Введите корректное положительное число.")

@dp.message(FinanceState.entering_comment)
async def add_tx_comment(message: types.Message, state: FSMContext):
    await state.update_data(comment=message.text)
    await save_transaction(message, state)

async def save_transaction(message: types.Message, state: FSMContext):
    d = await state.get_data()
    uid = message.from_user.id
    month = get_current_month()
    now = datetime.now().strftime("%d.%m %H:%M")
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.cursor().execute(
            "INSERT INTO transactions (user_id, type, category, amount, date, month_year, comment) VALUES (?,?,?,?,?,?,?)",
            (uid, d['transaction_type'], d['category'], d['amount'], now, month, d.get('comment', '—'))
        )
    
    await state.clear()
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🏠 В меню", callback_data="to_main"))
    await message.answer(f"✅ Успешно сохранено!\n{d['category']}: {d['amount']}₽", reply_markup=builder.as_markup())

# --- СТАТИСТИКА И АНАЛИТИКА ---
@dp.callback_query(F.data == "show_stats")
async def show_stats(cb: types.CallbackQuery):
    uid, month = cb.from_user.id, get_current_month()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id=? AND month_year=? GROUP BY type", (uid, month))
        totals = dict(c.fetchall())
        c.execute("SELECT monthly_limit FROM user_limits WHERE user_id=?", (uid,))
        limit = (c.fetchone() or [0])[0]
        c.execute("SELECT category, SUM(amount) FROM transactions WHERE user_id=? AND type='expense' AND month_year=? GROUP BY category ORDER BY SUM(amount) DESC", (uid, month))
        cats = c.fetchall()

    inc, exp = totals.get('income', 0), totals.get('expense', 0)
    res = f"📊 <b>Статистика {month}</b>\n\n🟢 Доход: <code>{inc:.2f}₽</code>\n🔴 Расход: <code>{exp:.2f}₽</code>\n"
    
    if limit > 0:
        p = (exp / limit * 100)
        res += f"\n🎯 <b>Лимит трат:</b>\n{generate_progress_bar(p)} {p:.1f}%\n({exp:.0f} из {limit:.0f}₽)\n"
    
    if exp > 0:
        res += "\n<b>По категориям:</b>\n"
        for cat, val in cats:
            res += f"• {cat}: {val:.0f}₽ ({(val/exp*100):.1f}%)\n"
            
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    await cb.message.answer(res, reply_markup=builder.as_markup(), parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data == "show_misc_details")
async def show_misc(cb: types.CallbackQuery):
    uid, month = cb.from_user.id, get_current_month()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT category, amount, comment, date FROM transactions WHERE user_id=? AND month_year=? AND (category LIKE '%Прочее%' OR category LIKE '%Другое%')", (uid, month))
        items = c.fetchall()
    
    res = "🔍 <b>Детализация 'Прочее':</b>\n\n" if items else "В 'Прочее' пока пусто."
    for cat, amt, comm, dt in items:
        res += f"📅 {dt}\n💰 {amt}₽ — <i>{comm}</i>\n\n"
    
    await cb.message.answer(res, reply_markup=InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main")).as_markup(), parse_mode="HTML")
    await cb.answer()

# --- ЛИМИТЫ, ПОДПИСКИ, ЭКСПОРТ ---
@dp.callback_query(F.data == "set_limit_start")
async def set_limit_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(FinanceState.setting_limit)
    await cb.message.answer("🎯 Введите желаемый лимит трат на месяц:")
    await cb.answer()

@dp.message(FinanceState.setting_limit)
async def set_limit_finish(m: types.Message, state: FSMContext):
    try:
        val = float(m.text.replace(",", "."))
        with sqlite3.connect(DB_PATH) as conn:
            conn.cursor().execute("INSERT OR REPLACE INTO user_limits (user_id, monthly_limit) VALUES (?, ?)", (m.from_user.id, val))
        await state.clear()
        await m.answer(f"✅ Лимит {val}₽ сохранен!")
    except: await m.answer("⚠️ Введите число.")

@dp.callback_query(F.data == "manage_subs")
async def manage_subs(cb: types.CallbackQuery):
    uid = cb.from_user.id
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, amount, day FROM subscriptions WHERE user_id=?", (uid,))
        subs = c.fetchall()
    
    res = "📅 <b>Регулярные платежи:</b>\n\n"
    builder = InlineKeyboardBuilder()
    if not subs: res += "Список пуст."
    else:
        for sid, name, amt, day in subs:
            res += f"• {day} число: <b>{name}</b> — {amt}₽\n"
            builder.row(types.InlineKeyboardButton(text=f"❌ Удалить {name}", callback_data=f"delsub_{sid}"))
    
    builder.row(types.InlineKeyboardButton(text="➕ Добавить", callback_data="add_sub_start"),
                types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    await cb.message.answer(res, reply_markup=builder.as_markup(), parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data == "add_sub_start")
async def add_sub_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(FinanceState.adding_subscription)
    await cb.message.answer("Введите название и сумму через пробел\n(Например: <code>Связь 500</code>):", parse_mode="HTML")
    await cb.answer()

@dp.message(FinanceState.adding_subscription)
async def add_sub_finish(m: types.Message, state: FSMContext):
    try:
        parts = m.text.split()
        name, amt = " ".join(parts[:-1]), float(parts[-1])
        with sqlite3.connect(DB_PATH) as conn:
            conn.cursor().execute("INSERT INTO subscriptions (user_id, name, amount, day) VALUES (?,?,?,?)", (m.from_user.id, name, amt, datetime.now().day))
        await state.clear()
        await m.answer(f"✅ Подписка '{name}' добавлена.")
    except: await m.answer("⚠️ Ошибка. Формат: Название Сумма")

@dp.callback_query(F.data == "export_csv")
async def export_csv(cb: types.CallbackQuery):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT date, type, category, amount, comment FROM transactions WHERE user_id=?", (cb.from_user.id,))
        rows = c.fetchall()
    
    if not rows:
        await cb.answer("Данных нет.")
        return

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Дата', 'Тип', 'Категория', 'Сумма', 'Комментарий'])
    cw.writerows(rows)
    buf = si.getvalue().encode('utf-8-sig')
    await cb.message.answer_document(types.BufferedInputFile(buf, filename="report.csv"), caption="📊 Ваш финансовый отчет.")
    await cb.answer()

# --- МИНИ-ИГРА СЛОТЫ ---
@dp.callback_query(F.data == "play_game")
async def play_game(cb: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🎰 Крутить!", callback_data="spin_slots"),
                types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    await cb.message.answer("🎰 <b>Finance Slots</b>\nИгра на удачу!", reply_markup=builder.as_markup(), parse_mode="HTML")
    await cb.answer()

@dp.callback_query(F.data == "spin_slots")
async def spin_slots(cb: types.CallbackQuery):
    syms = ["💎", "💰", "💵", "🍎", "🚗", "7️⃣"]
    res = [random.choice(syms) for _ in range(3)]
    res_str = f"| {' | '.join(res)} |"
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🎰 Еще!", callback_data="spin_slots"),
                                          types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    await cb.message.edit_text(f"🎰 РЕЗУЛЬТАТ:\n\n<code>{res_str}</code>", reply_markup=builder.as_markup(), parse_mode="HTML")

# --- УДАЛЕНИЕ И АРХИВ ---
@dp.callback_query(F.data == "manage_delete")
async def manage_del(cb: types.CallbackQuery):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, category, amount FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 5", (cb.from_user.id,))
        items = c.fetchall()
    
    builder = InlineKeyboardBuilder()
    for tid, cat, amt in items:
        builder.row(types.InlineKeyboardButton(text=f"❌ {amt}₽ - {cat}", callback_data=f"del_{tid}"))
    builder.row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    await cb.message.edit_text("Что удалить (последние 5)?", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("del_"))
async def process_del(cb: types.CallbackQuery):
    tid = cb.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        conn.cursor().execute("DELETE FROM transactions WHERE id=?", (tid,))
    await cb.answer("Удалено!")
    await manage_del(cb)

@dp.callback_query(F.data == "show_archive")
async def show_archive(cb: types.CallbackQuery):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT month_year FROM transactions WHERE user_id=? ORDER BY id DESC", (cb.from_user.id,))
        months = [r[0] for r in c.fetchall()]
    
    builder = InlineKeyboardBuilder()
    for m in months: builder.row(types.InlineKeyboardButton(text=f"📂 {m}", callback_data=f"arch_{m}"))
    builder.row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    await cb.message.edit_text("Архив по месяцам:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("arch_"))
async def show_arch_month(cb: types.CallbackQuery):
    m = cb.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id=? AND month_year=? GROUP BY type", (cb.from_user.id, m))
        totals = dict(c.fetchall())
    res = f"📂 Архив: <b>{m}</b>\n\n📈 Доход: {totals.get('income',0):.0f}₽\n📉 Расход: {totals.get('expense',0):.0f}₽"
    await cb.message.answer(res, reply_markup=InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main")).as_markup(), parse_mode="HTML")

# --- СИСТЕМНОЕ ---
@dp.callback_query(F.data == "to_main")
async def to_main(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await start_cmd(cb.message, state)
    try: await cb.message.delete()
    except: pass

async def start_web():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", 10000))).start()

async def main():
    await start_web()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
