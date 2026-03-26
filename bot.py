import asyncio
import logging
import sqlite3
import os
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiohttp import web, ClientSession

# --- CONFIGURATION ---
API_TOKEN = "7799961207:AAEPNytcZZ8iseximsxmSDD6j-IrSW25hD8"
# Используйте корректный file_id фото или оставьте заглушку
MAIN_MENU_PHOTO = "AgACAgIAAxkBAAEY..." 

# Прямо указываем твой URL для механизма анти-сна как запасной вариант
APP_URL = os.environ.get("APP_URL", "https://finance-bot-8zns.onrender.com")

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
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, category TEXT, 
                       amount REAL, date TEXT, month_year TEXT, comment TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_limits 
                      (user_id INTEGER PRIMARY KEY, monthly_limit REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS subscriptions 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, name TEXT, amount REAL, day INTEGER)''')
    conn.commit()
    conn.close()

init_db()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_current_month():
    return datetime.now().strftime("%m.%Y")

def generate_progress_bar(percent, length=10):
    percent = max(0, min(100, percent))
    filled = int(length * percent / 100)
    return '🔵' * filled + '⚪' * (length - filled)

# --- АНТИ-СОН (KEEP ALIVE) ---
async def keep_alive():
    if not APP_URL:
        logger.warning("KEEP_ALIVE: APP_URL не задан и не найден в коде. Анти-сон отключен.")
        return
        
    logger.info(f"KEEP_ALIVE: Запускаю пинг на адрес {APP_URL} каждые 14 минут...")
    await asyncio.sleep(30) # Ждем 30 секунд после запуска, чтобы веб-сервер точно поднялся
    
    while True:
        try:
            async with ClientSession() as session:
                async with session.get(APP_URL, timeout=10) as resp:
                    if resp.status == 200:
                        logger.info("KEEP_ALIVE: Внутренний пинг успешен.")
                    else:
                        logger.warning(f"KEEP_ALIVE: Сервер ответил статусом {resp.status}")
        except Exception as e:
            logger.error(f"KEEP_ALIVE: Ошибка внутреннего пинга: {e}")
        # Задержка 14 минут (840 секунд) - как раз перед отключением Render (15 минут)
        await asyncio.sleep(840)

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    await send_main_menu(message.chat.id, message.from_user.id)

async def send_main_menu(chat_id: int, user_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT monthly_limit FROM user_limits WHERE user_id=?", (user_id,))
        res_limit = c.fetchone()
        user_limit = res_limit[0] if res_limit else 0

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="➕ Операция", callback_data="add_transaction"),
                types.InlineKeyboardButton(text="📅 Подписки", callback_data="manage_subs"))
    builder.row(types.InlineKeyboardButton(text="📊 Статистика", callback_data="show_stats"),
                types.InlineKeyboardButton(text="🎯 Лимит", callback_data="set_limit_start"))
    builder.row(types.InlineKeyboardButton(text="🔍 Детализация", callback_data="show_misc_details"),
                types.InlineKeyboardButton(text="📜 Архив", callback_data="show_archive"))
    builder.row(types.InlineKeyboardButton(text="🗑 Удалить", callback_data="manage_delete"),
                types.InlineKeyboardButton(text="🕹 Мини-игра", callback_data="play_game"))
    
    caption = (
        f"🥷🏿 <b>Finance Pro [v3.5]</b>\n\n"
        f"🎯 <b>Лимит:</b> {user_limit if user_limit > 0 else 'не задан'}₽\n"
        f"📅 <b>Месяц:</b> {get_current_month()}\n\n"
        "Выберите действие в меню:"
    )

    try:
        await bot.send_photo(chat_id=chat_id, photo=MAIN_MENU_PHOTO, caption=caption, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception:
        await bot.send_message(chat_id=chat_id, text=caption, reply_markup=builder.as_markup(), parse_mode="HTML")

# --- ЛОГИКА ОПЕРАЦИЙ ---
@dp.callback_query(F.data == "add_transaction")
async def add_tx_start(cb: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="📉 Расход", callback_data="type_expense"), 
                types.InlineKeyboardButton(text="📈 Доход", callback_data="type_income"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="to_main"))
    await state.set_state(FinanceState.choosing_type)
    await cb.message.edit_text("Выберите тип операции:", reply_markup=builder.as_markup())
    await cb.answer()

@dp.callback_query(FinanceState.choosing_type, F.data.startswith("type_"))
async def add_tx_type(cb: types.CallbackQuery, state: FSMContext):
    t_type = "expense" if cb.data == "type_expense" else "income"
    await state.update_data(transaction_type=t_type)
    cats = EXPENSE_CATEGORIES if t_type == "expense" else INCOME_CATEGORIES
    
    builder = InlineKeyboardBuilder()
    for cat in cats: 
        builder.add(types.InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}"))
    builder.adjust(2).row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="add_transaction"))
    
    await state.set_state(FinanceState.choosing_category)
    await cb.message.edit_text(f"Тип: {'Расход' if t_type=='expense' else 'Доход'}\nВыберите категорию:", reply_markup=builder.as_markup())

@dp.callback_query(FinanceState.choosing_category, F.data.startswith("cat_"))
async def add_tx_cat(cb: types.CallbackQuery, state: FSMContext):
    category = cb.data.split("_")[1]
    await state.update_data(category=category)
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад к категориям", callback_data=f"type_{(await state.get_data())['transaction_type']}"))
    
    await state.set_state(FinanceState.entering_amount)
    await cb.message.edit_text(f"Категория: <b>{category}</b>\nВведите сумму (числом):", reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.message(FinanceState.entering_amount)
async def add_tx_amt(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
        await state.update_data(amount=amount)
        data = await state.get_data()
        
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
    await message.answer(f"✅ Сохранено!\n{d['category']}: {d['amount']}₽", reply_markup=builder.as_markup())

# --- УСТАНОВКА ЛИМИТА ---
@dp.callback_query(F.data == "set_limit_start")
async def set_limit_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(FinanceState.setting_limit)
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="⬅️ Отмена", callback_data="to_main"))
    await cb.message.edit_text("🎯 Введите желаемый лимит трат на месяц:", reply_markup=builder.as_markup())
    await cb.answer()

@dp.message(FinanceState.setting_limit)
async def set_limit_finish(m: types.Message, state: FSMContext):
    try:
        val = float(m.text.replace(",", "."))
        with sqlite3.connect(DB_PATH) as conn:
            conn.cursor().execute("INSERT OR REPLACE INTO user_limits (user_id, monthly_limit) VALUES (?, ?)", (m.from_user.id, val))
        await state.clear()
        await m.answer(f"✅ Лимит {val}₽ успешно установлен!")
        await send_main_menu(m.chat.id, m.from_user.id)
    except: 
        await m.answer("⚠️ Введите число.")

# --- ПОДПИСКИ ---
@dp.callback_query(F.data == "manage_subs")
async def manage_subs(cb: types.CallbackQuery):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, amount, day FROM subscriptions WHERE user_id=?", (cb.from_user.id,))
        subs = c.fetchall()
    
    res = "📅 <b>Ваши подписки:</b>\n\n"
    builder = InlineKeyboardBuilder()
    if not subs: res += "Список пуст."
    else:
        for sid, name, amt, day in subs:
            res += f"▫️ {name}: {amt}₽ (день: {day})\n"
            builder.row(types.InlineKeyboardButton(text=f"❌ Удалить {name}", callback_data=f"delsub_{sid}"))
    
    builder.row(types.InlineKeyboardButton(text="➕ Добавить", callback_data="add_sub_start"),
                types.InlineKeyboardButton(text="⬅️ Меню", callback_data="to_main"))
    await cb.message.edit_text(res, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "add_sub_start")
async def add_sub_start(cb: types.CallbackQuery, state: FSMContext):
    await state.set_state(FinanceState.adding_subscription)
    await cb.message.edit_text("Введите название, сумму и день месяца через пробел\n(Пример: <i>Netflix 800 15</i>):", parse_mode="HTML")

@dp.message(FinanceState.adding_subscription)
async def add_sub_finish(m: types.Message, state: FSMContext):
    try:
        parts = m.text.split()
        name, amt, day = parts[0], float(parts[1]), int(parts[2])
        with sqlite3.connect(DB_PATH) as conn:
            conn.cursor().execute("INSERT INTO subscriptions (user_id, name, amount, day) VALUES (?,?,?,?)", (m.from_user.id, name, amt, day))
        await state.clear()
        await m.answer(f"✅ Подписка {name} добавлена!")
        await send_main_menu(m.chat.id, m.from_user.id)
    except:
        await m.answer("⚠️ Ошибка. Формат: Название Сумма День")

@dp.callback_query(F.data.startswith("delsub_"))
async def del_sub(cb: types.CallbackQuery):
    sid = cb.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        conn.cursor().execute("DELETE FROM subscriptions WHERE id=?", (sid,))
    await cb.answer("Подписка удалена")
    await manage_subs(cb)

# --- СТАТИСТИКА И АРХИВ ---
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
        res += f"\n🎯 <b>Лимит:</b>\n{generate_progress_bar(p)} {p:.1f}%\n"
    if exp > 0:
        res += "\n<b>Категории:</b>\n"
        for cat, val in cats: res += f"• {cat}: {val:.0f}₽\n"
            
    await cb.message.edit_text(res, reply_markup=InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main")).as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "show_archive")
async def show_archive(cb: types.CallbackQuery):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT month_year FROM transactions WHERE user_id=? ORDER BY id DESC", (cb.from_user.id,))
        months = [r[0] for r in c.fetchall()]
    
    if not months: return await cb.answer("Архив пуст")
    builder = InlineKeyboardBuilder()
    for m in months: builder.row(types.InlineKeyboardButton(text=f"📂 {m}", callback_data=f"arch_{m}"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Меню", callback_data="to_main"))
    await cb.message.edit_text("Выберите месяц из архива:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("arch_"))
async def show_arch_month(cb: types.CallbackQuery):
    month = cb.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id=? AND month_year=? GROUP BY type", (cb.from_user.id, month))
        res = dict(c.fetchall())
    inc, exp = res.get('income', 0), res.get('expense', 0)
    text = f"📂 <b>Архив за {month}</b>\n\n📈 Доход: {inc}₽\n📉 Расход: {exp}₽\n💰 Баланс: {inc-exp}₽"
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="⬅️ К списку", callback_data="show_archive"))
    await cb.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "show_misc_details")
async def show_misc(cb: types.CallbackQuery):
    uid, month = cb.from_user.id, get_current_month()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT amount, comment, date FROM transactions WHERE user_id=? AND month_year=? AND (category LIKE '%Прочее%' OR category LIKE '%Другое%')", (uid, month))
        items = c.fetchall()
    res = "🔍 <b>Детали 'Прочего':</b>\n\n"
    if not items: res += "Записей нет."
    else:
        for a, c, d in items: res += f"📍 {d}: {a}₽ ({c})\n"
    await cb.message.edit_text(res, reply_markup=InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="⬅️ Меню", callback_data="to_main")).as_markup(), parse_mode="HTML")

# --- УДАЛЕНИЕ ---
@dp.callback_query(F.data == "manage_delete")
async def manage_del(cb: types.CallbackQuery):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, category, amount FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 5", (cb.from_user.id,))
        items = c.fetchall()
    if not items: return await cb.answer("Операций не найдено")
    builder = InlineKeyboardBuilder()
    for tid, cat, amt in items: builder.row(types.InlineKeyboardButton(text=f"❌ {amt}₽ - {cat}", callback_data=f"delop_{tid}"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Меню", callback_data="to_main"))
    await cb.message.edit_text("Выберите операцию для удаления:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("delop_"))
async def del_op(cb: types.CallbackQuery):
    tid = cb.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        conn.cursor().execute("DELETE FROM transactions WHERE id=?", (tid,))
    await cb.answer("Удалено")
    await manage_del(cb)

# --- ИГРА ---
@dp.callback_query(F.data == "play_game")
async def play_game(cb: types.CallbackQuery):
    await cb.message.answer_dice(emoji=random.choice(["🎲", "🎰", "🎯"]))
    await cb.answer("Удачи!")

@dp.callback_query(F.data == "to_main")
async def to_main(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    try: await cb.message.delete()
    except: pass
    await send_main_menu(cb.message.chat.id, cb.from_user.id)

# --- WEB SERVER & MAIN ---
async def start_web():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="Bot is active!"))
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    await web.TCPSite(runner, "0.0.0.0", port).start()

async def main():
    await start_web()
    asyncio.create_task(keep_alive())
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
