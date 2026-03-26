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
    
    # Здесь мы обновили название на МаниХелпер🥷🏿
    await message.answer(
        f"🥷🏿 <b>МаниХелпер</b>\n"
        f"Привет, {user_name}!\n"
        f"Ваш личный финансовый помощник готов к работе.\n\n"
        f"Текущий месяц: <code>{get_current_month()}</code>\n\n"
        "Выберите действие:", 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Категории
EXPENSE_CATEGORIES = [
    "🍎 Продукты", "☕️ Кафе/Рестораны", 
    "🚗 Транспорт", "🏠 Жилье/ЖКХ", 
    "📱 Связь", "🎁 Подарки", 
    "💊 Здоровье", "👕 Одежда", 
    "🎮 Досуг", "🛒 Прочее"
]

INCOME_CATEGORIES = [
    "💰 Зарплата", "💵 Аванс", 
    "📈 Инвестиции", "💳 Фриланс", 
    "➕ Другое"
]

# --- СОСТОЯНИЯ (FSM) ---
class FinanceState(StatesGroup):
    choosing_type = State()
    choosing_category = State()
    entering_amount = State()
    entering_comment = State()

# --- БАЗА ДАННЫХ ---
DB_PATH = 'finance_manager.db'

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS transactions 
                          (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                           user_id INTEGER, 
                           type TEXT, 
                           category TEXT, 
                           amount REAL, 
                           date TEXT,
                           month_year TEXT,
                           comment TEXT)''')
        conn.commit()
        logger.info("Database initialized successfully.")
        return conn
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        return None

db_conn = init_db()

def get_current_month():
    return datetime.now().strftime("%m.%Y")

def generate_progress_bar(percent, length=10):
    filled_length = int(length * percent / 100)
    bar = '🔵' * filled_length + '⚪' * (length - filled_length)
    return bar

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
        f"💎 <b>ДебитКредит: Личный Казначей</b>\n"
        f"Привет, {user_name}!\n"
        f"Ваш личный финансовый помощник готов к работе.\n\n"
        f"Текущий месяц: <code>{get_current_month()}</code>\n\n"
        "Выберите действие:", 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "add_transaction")
async def add_transaction_start(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    builder = InlineKeyboardBuilder()
    builder.add(types.InlineKeyboardButton(text="📉 Расход", callback_data="type_expense"))
    builder.add(types.InlineKeyboardButton(text="📈 Доход", callback_data="type_income"))
    
    await state.set_state(FinanceState.choosing_type)
    await callback_query.message.edit_text("Что добавляем?", reply_markup=builder.as_markup())

@dp.callback_query(FinanceState.choosing_type, F.data.startswith("type_"))
async def choose_category(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    t_type = "expense" if callback_query.data == "type_expense" else "income"
    await state.update_data(transaction_type=t_type)
    
    categories = EXPENSE_CATEGORIES if t_type == "expense" else INCOME_CATEGORIES
    builder = InlineKeyboardBuilder()
    for cat in categories:
        builder.add(types.InlineKeyboardButton(text=cat, callback_data=f"cat_{cat}"))
    builder.adjust(2)
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="add_transaction"))
    
    await state.set_state(FinanceState.choosing_category)
    await callback_query.message.edit_text("Выберите категорию:", reply_markup=builder.as_markup())

@dp.callback_query(FinanceState.choosing_category, F.data.startswith("cat_"))
async def enter_amount_prompt(callback_query: types.CallbackQuery, state: FSMContext):
    await callback_query.answer()
    category = callback_query.data.split("_")[1]
    await state.update_data(category=category)
    await state.set_state(FinanceState.entering_amount)
    await callback_query.message.edit_text(
        f"Категория: <b>{category}</b>\n\n"
        f"✍️ <b>Введите сумму числом</b>\n(например: 500 или 1250.50):", 
        parse_mode="HTML"
    )

@dp.message(FinanceState.entering_amount)
async def process_amount(message: types.Message, state: FSMContext):
    raw_text = message.text.replace(" ", "").replace(",", ".")
    try:
        amount = float(raw_text)
        if amount <= 0: raise ValueError
    except ValueError:
        await message.answer("⚠️ Пожалуйста, введите корректное число больше нуля.")
        return

    await state.update_data(amount=amount)
    user_data = await state.get_data()
    category = user_data.get('category', 'Прочее')

    if "Прочее" in category or "Другое" in category:
        await state.set_state(FinanceState.entering_comment)
        await message.answer(f"📝 Вы выбрали '{category}'. Напишите краткое описание операции:")
    else:
        await save_transaction(message, state)

@dp.message(FinanceState.entering_comment)
async def process_comment(message: types.Message, state: FSMContext):
    await state.update_data(comment=message.text)
    await save_transaction(message, state)

async def save_transaction(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    t_type = user_data.get('transaction_type')
    category = user_data.get('category')
    amount = user_data.get('amount')
    comment = user_data.get('comment', None)
    user_id = message.from_user.id
    
    now = datetime.now()
    date_full = now.strftime("%Y-%m-%d %H:%M")
    month_year = now.strftime("%m.%Y")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO transactions (user_id, type, category, amount, date, month_year, comment) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, t_type, category, amount, date_full, month_year, comment)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"Error saving to DB: {e}")
        await message.answer("❌ Произошла ошибка при сохранении. Попробуйте позже.")
        await state.clear()
        return

    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🏠 Главное меню", callback_data="to_main"))
    
    label = "Расход 📉" if t_type == "expense" else "Доход 📈"
    comment_str = f"\n<b>Описание:</b> {comment}" if comment else ""
    
    await message.answer(
        f"✅ <b>Запись добавлена!</b>\n\n"
        f"<b>Тип:</b> {label}\n"
        f"<b>Категория:</b> {category}{comment_str}\n"
        f"<b>Сумма:</b> {amount:.2f} ₽\n"
        f"<b>Месяц:</b> {month_year}", 
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "show_stats")
async def show_stats(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    current_m = get_current_month()
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT type, SUM(amount) FROM transactions WHERE user_id = ? AND month_year = ? GROUP BY type", (user_id, current_m))
        totals = dict(cursor.fetchall())
        income = totals.get('income', 0)
        expense = totals.get('expense', 0)
        
        cursor.execute("SELECT category, SUM(amount) FROM transactions WHERE user_id = ? AND type = 'expense' AND month_year = ? GROUP BY category ORDER BY SUM(amount) DESC", (user_id, current_m))
        cats_data = cursor.fetchall()

    res = (f"📅 <b>Итоги за {current_m}:</b>\n\n"
            f"📈 Доход: <code>{income:.2f} ₽</code>\n"
            f"📉 Расход: <code>{expense:.2f} ₽</code>\n"
            f"💰 Остаток: <b>{income - expense:.2f} ₽</b>\n\n"
            f"📊 <b>Распределение трат:</b>\n")
    
    if not cats_data:
        res += "<i>Записей пока нет</i>"
    else:
        for cat, val in cats_data:
            percentage = (val / expense * 100) if expense > 0 else 0
            bar = generate_progress_bar(percentage)
            res += f"<b>{cat}</b>: {val:.2f}₽ ({percentage:.1f}%)\n{bar}\n\n"

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🏠 В меню", callback_data="to_main"))
    
    try:
        await callback_query.message.edit_text(res, reply_markup=builder.as_markup(), parse_mode="HTML")
    except TelegramBadRequest:
        await callback_query.answer()

@dp.callback_query(F.data == "show_misc_details")
async def show_misc_details(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    current_m = get_current_month()
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT type, amount, comment, date FROM transactions 
               WHERE user_id = ? AND month_year = ? 
               AND (category LIKE '%Прочее%' OR category LIKE '%Другое%')
               ORDER BY id DESC""", (user_id, current_m)
        )
        rows = cursor.fetchall()
    
    if not rows:
        await callback_query.answer("Записей в категориях 'Прочее/Другое' нет", show_alert=True)
        return

    res = f"🔍 <b>Детализация 'Прочее' ({current_m}):</b>\n\n"
    for t_type, amt, comment, dt in rows:
        sign = "🔴 -" if t_type == "expense" else "🟢 +"
        desc = comment if comment else "без описания"
        res += f"{sign}{amt:.2f} | {desc} <i>({dt})</i>\n"

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🏠 В меню", callback_data="to_main"))
    await callback_query.message.edit_text(res, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "manage_delete")
async def manage_delete(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    current_m = get_current_month()
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, type, category, amount, comment FROM transactions WHERE user_id = ? AND month_year = ? ORDER BY id DESC LIMIT 10", 
            (user_id, current_m)
        )
        rows = cursor.fetchall()
    
    if not rows:
        await callback_query.answer("В этом месяце операций еще нет", show_alert=True)
        return

    res = "🗑 <b>Выберите операцию для удаления:</b>\n(Показаны последние 10)\n\n"
    builder = InlineKeyboardBuilder()
    for r in rows:
        t_id, t_type, cat, amt, comment = r
        sign = "+" if t_type == "income" else "-"
        display_name = comment if comment else cat
        if len(display_name) > 15: display_name = display_name[:12] + "..."
        btn_text = f"{sign}{amt:.0f} | {display_name}"
        builder.row(types.InlineKeyboardButton(text=btn_text, callback_data=f"del_confirm_{t_id}"))
    
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="to_main"))
    await callback_query.message.edit_text(res, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data.startswith("del_confirm_"))
async def execute_delete(callback_query: types.CallbackQuery):
    t_id = callback_query.data.split("_")[2]
    user_id = callback_query.from_user.id
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?", (t_id, user_id))
        conn.commit()
        
    await callback_query.answer("Операция успешно удалена", show_alert=True)
    await manage_delete(callback_query)

@dp.callback_query(F.data == "show_archive")
async def show_archive(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT month_year, 
                      SUM(CASE WHEN type='income' THEN amount ELSE 0 END),
                      SUM(CASE WHEN type='expense' THEN amount ELSE 0 END)
               FROM transactions WHERE user_id = ? 
               GROUP BY month_year ORDER BY id DESC""", (user_id,)
        )
        history = cursor.fetchall()
    
    if not history:
        await callback_query.answer("История операций пуста", show_alert=True)
        return

    res = "📜 <b>Архив по месяцам:</b>\n\n"
    for m, inc, exp in history:
        res += f"🔘 <b>{m}</b>\n⬆️ +{inc:.2f} | ⬇️ -{exp:.2f}\n\n"

    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🏠 В меню", callback_data="to_main"))
    await callback_query.message.edit_text(res, reply_markup=builder.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "to_main")
async def to_main_menu(callback_query: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await start_cmd(callback_query.message, state)
    await callback_query.answer()

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (Новое) ---
async def handle_health(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server started on port {port}")

# --- ЗАПУСК ---
async def main():
    # Запуск веб-сервера в фоне
    asyncio.create_task(start_web_server())
    
    logger.info("Bot is starting polling...")
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot manually stopped.")
    except Exception as e:
        logger.critical(f"Critical error: {e}")
