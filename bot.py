import asyncio
import logging
import sqlite3
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramConflictError
from aiohttp import web

# --- КОНФИГУРАЦИЯ ---
API_TOKEN = "7799961207:AAEPNytcZZ8iseximsxmSDD6j-IrSW25hD8"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Категории
EXPENSE_CATEGORIES = ["🍎 Продукты", "☕️ Кафе/Рестораны", "🚗 Транспорт", "🏠 Жилье/ЖКХ", "📱 Связь", "🎁 Подарки", "💊 Здоровье", "👕 Одежда", "🎮 Досуг", "🛒 Прочее"]
INCOME_CATEGORIES = ["💰 Зарплата", "💵 Аванс", "📈 Инвестиции", "💳 Фриланс", "➕ Другое"]

class FinanceState(StatesGroup):
    choosing_type = State()
    choosing_category = State()
    entering_amount = State()
    entering_comment = State()

DB_PATH = 'finance_manager.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, category TEXT, amount REAL, date TEXT, month_year TEXT, comment TEXT)''')
    conn.commit()
    return conn

init_db()

def get_current_month():
    return datetime.now().strftime("%m.%Y")

def generate_progress_bar(percent, length=10):
    filled_length = int(length * percent / 100)
    return '🔵' * filled_length + '⚪' * (length - filled_length)

# --- ОБРАБОТЧИКИ ---

@dp.message(Command("start"))
async def start_cmd(message: types.Message, state: FSMContext):
    await state.clear()
    user_name = message.from_user.first_name
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="➕ Добавить операцию", callback_data="add_transaction"))
    builder.row(types.InlineKeyboardButton(text="📊 Статистика месяца", callback_data="show_stats"))
    builder.row(types.InlineKeyboardButton(text="🔍 Детализация (Прочее)", callback_data="show_misc_details"))
    builder.row(types.InlineKeyboardButton(text="📜 Архив месяцев", callback_data="show_archive"))
    builder.row(types.InlineKeyboardButton(text="🗑 Удалить операцию", callback_data="manage_delete"))
    
    await message.answer(
        f"🥷🏿 <b>МаниХелпер</b>\n"
        f"Привет, {user_name}!\n"
        f"Ваш личный финансовый помощник готов к работе.\n\n"
        f"Текущий месяц: <code>{get_current_month()}</code>\n\n"
        "Выберите действие:", 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "add_transaction")
async def add_transaction_start(callback_query: types.CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="📉 Расход", callback_data="type_expense"), types.InlineKeyboardButton(text="📈 Доход", callback_data="type_income"))
    await state.set_state(FinanceState.choosing_type)
    await callback_query.message.edit_text("Что добавляем?", reply_markup=builder.as_markup())

@dp.callback_query(FinanceState.choosing_type, F.data.startswith("type_"))
async def choose_category(callback_query: types.CallbackQuery, state: FSMContext):
    t_type = "expense" if callback_query.data == "type_expense" else "income"
    await state.update_data(transaction_type=t_type)
    categories = EXPENSE_CATEGORIES if t_type == "expense" else INCOME_CATEGORIES
    builder = InlineKeyboardBuilder()
    for cat in categories: builder.add(types.InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}"))
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="add_transaction"))
    await state.set_state(FinanceState.choosing_category)
    await callback_query.message.edit_text("Выберите категорию:", reply_markup=builder.as_markup())

@dp.callback_query(FinanceState.choosing_category, F.data.startswith("cat_"))
async def enter_amount_prompt(callback_query: types.CallbackQuery, state: FSMContext):
    category = callback_query.data.split("_")[1]
    await state.update_data(category=category)
    await state.set_state(FinanceState.entering_amount)
    await callback_query.message.edit_text(f"Категория: <b>{category}</b>\nВведите сумму числом:", parse_mode="HTML")

@dp.message(FinanceState.entering_amount)
async def process_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0: raise ValueError
    except:
        await message.answer("⚠️ Введите число больше нуля.")
        return
    await state.update_data(amount=amount)
    data = await state.get_data()
    if "Прочее" in data['category'] or "Другое" in data['category']:
        await state.set_state(FinanceState.entering_comment)
        await message.answer("📝 Напишите описание (за что именно):")
    else:
        await save_tx(message, state)

@dp.message(FinanceState.entering_comment)
async def process_comment(message: types.Message, state: FSMContext):
    await state.update_data(comment=message.text)
    await save_tx(message, state)

async def save_tx(message: types.Message, state: FSMContext):
    d = await state.get_data()
    uid = message.from_user.id
    cur_m = get_current_month()
    comment = d.get('comment')
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        # Сохраняем операцию
        cursor.execute(
            "INSERT INTO transactions (user_id, type, category, amount, date, month_year, comment) VALUES (?,?,?,?,?,?,?)",
            (uid, d['transaction_type'], d['category'], d['amount'], 
             datetime.now().strftime("%Y-%m-%d %H:%M"), cur_m, comment)
        )
        # Считаем итог по этой категории за месяц
        cursor.execute(
            "SELECT SUM(amount) FROM transactions WHERE user_id=? AND category=? AND month_year=?",
            (uid, d['category'], cur_m)
        )
        cat_total = cursor.fetchone()[0] or 0
        
    await state.clear()
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    
    # Формируем расширенное подтверждение с учетом комментария
    msg_text = (
        f"✅ <b>Запись сохранена!</b>\n\n"
        f"🥷🏿 <b>МаниХелпер</b> сообщает:\n"
        f"Категория: <b>{d['category']}</b>\n"
        f"Сумма: <code>{d['amount']:.2f}₽</code>\n"
    )
    
    if comment:
        msg_text += f"Описание: <i>{comment}</i>\n"
        
    msg_text += f"Всего в этой категории за месяц: <b>{cat_total:.2f}₽</b>"
    
    await message.answer(msg_text, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "show_stats")
async def show_stats(callback_query: types.CallbackQuery):
    uid, cur_m = callback_query.from_user.id, get_current_month()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id=? AND month_year=? GROUP BY type", (uid, cur_m))
        totals = dict(c.fetchall())
        inc, exp = totals.get('income', 0), totals.get('expense', 0)
        c.execute("SELECT category, SUM(amount) FROM transactions WHERE user_id=? AND type='expense' AND month_year=? GROUP BY category ORDER BY SUM(amount) DESC", (uid, cur_m))
        cats = c.fetchall()
    
    res = f"📅 Статистика <b>{cur_m}</b>\n\n📈 Доход: <code>{inc:.2f}₽</code>\n📉 Расход: <code>{exp:.2f}₽</code>\n💰 Остаток: <b>{inc-exp:.2f}₽</b>\n\n"
    if exp > 0:
        for cat, val in cats:
            p = (val/exp*100)
            res += f"<b>{cat}</b>: {val:.0f}₽ ({p:.1f}%)\n{generate_progress_bar(p)}\n"
    else:
        res += "Трат в этом месяце еще не было."
        
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    await callback_query.message.edit_text(res, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "show_misc_details")
async def show_misc_details(callback_query: types.CallbackQuery):
    uid, cur_m = callback_query.from_user.id, get_current_month()
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT category, amount, comment, date FROM transactions WHERE user_id=? AND month_year=? AND (category LIKE '%Прочее%' OR category LIKE '%Другое%')", (uid, cur_m))
        items = c.fetchall()
    
    if not items:
        res = "В категориях 'Прочее/Другое' пока нет записей."
    else:
        res = "🔍 <b>Детализация 'Прочее':</b>\n\n"
        for cat, amt, comm, dt in items:
            res += f"📍 {dt}\n💰 {amt}₽ - <i>{comm if comm else 'Без описания'}</i>\n\n"
            
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    await callback_query.message.edit_text(res, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "show_archive")
async def show_archive(callback_query: types.CallbackQuery):
    uid = callback_query.from_user.id
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT month_year FROM transactions WHERE user_id=? ORDER BY id DESC", (uid,))
        months = [row[0] for row in c.fetchall()]
    
    if not months:
        await callback_query.answer("Архив пуст.")
        return

    builder = InlineKeyboardBuilder()
    for m in months:
        builder.row(types.InlineKeyboardButton(text=f"📂 {m}", callback_data=f"archive_{m}"))
    builder.row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    await callback_query.message.edit_text("Выберите месяц из архива:", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("archive_"))
async def show_archive_month(callback_query: types.CallbackQuery):
    month = callback_query.data.split("_")[1]
    uid = callback_query.from_user.id
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id=? AND month_year=? GROUP BY type", (uid, month))
        totals = dict(c.fetchall())
        inc, exp = totals.get('income', 0), totals.get('expense', 0)
    
    res = f"📂 Архив: <b>{month}</b>\n\n📈 Доход: {inc:.2f}₽\n📉 Расход: {exp:.2f}₽\n💰 Итог: {inc-exp:.2f}₽"
    builder = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="⬅️ К списку", callback_data="show_archive"))
    await callback_query.message.edit_text(res, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "manage_delete")
async def manage_delete(callback_query: types.CallbackQuery):
    uid = callback_query.from_user.id
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT id, category, amount, date FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 10", (uid,))
        items = c.fetchall()
    
    if not items:
        await callback_query.answer("Нет операций для удаления.")
        return

    builder = InlineKeyboardBuilder()
    for tid, cat, amt, dt in items:
        builder.row(types.InlineKeyboardButton(text=f"❌ {amt}₽ - {cat} ({dt})", callback_data=f"del_{tid}"))
    builder.row(types.InlineKeyboardButton(text="🏠 Меню", callback_data="to_main"))
    await callback_query.message.edit_text("Выберите операцию для удаления (последние 10):", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("del_"))
async def process_delete(callback_query: types.CallbackQuery):
    tid = callback_query.data.split("_")[1]
    with sqlite3.connect(DB_PATH) as conn:
        conn.cursor().execute("DELETE FROM transactions WHERE id=?", (tid,))
    await callback_query.answer("Удалено!")
    await manage_delete(callback_query)

@dp.callback_query(F.data == "to_main")
async def to_main(cb: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await start_cmd(cb.message, state)

# --- WEB SERVER FOR RENDER ---
async def handle(request): return web.Response(text="Bot is alive")
async def start_web():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logger.info(f"Веб-сервер запущен на порту {port}")

async def main():
    # Запуск веб-сервера в фоне
    asyncio.create_task(start_web())
    
    while True:
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("МаниХелпер запускается...")
            await dp.start_polling(bot)
        except TelegramConflictError:
            logger.warning("Конфликт сессий! Ждем завершения старого процесса (20 сек)...")
            await asyncio.sleep(20)
        except Exception as e:
            logger.error(f"Ошибка в основном цикле: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")
