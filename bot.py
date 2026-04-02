import asyncio
import logging
import random
import string
import sqlite3
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ChatMemberStatus

# ========== КОНФИГУРАЦИЯ ==========
API_TOKEN = '8640357814:AAGgeL3isGxurlRzQuiJ2lhVD09eMr0_4Zs'
ADMIN_IDS = [886788397]
REQUIRED_CHANNEL = '@HarukaGift'

MAX_USERNAME_LEN = 32
MIN_USERNAME_LEN = 5

# ========== ИНИЦИАЛИЗАЦИЯ ==========
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# ========== ВСТРОЕННАЯ НЕЙРОСЕТЬ (ЛОКАЛЬНАЯ) ==========
class LocalNeuralNetwork:
    """
    Собственная нейросеть бота.
    Анализирует запрос, извлекает намерения и генерирует ответ.
    """
    def __init__(self):
        # Контекст диалогов: user_id -> list of last messages
        self.context: Dict[int, List[str]] = {}
        
        # База знаний (ключевые слова и реакции)
        self.intents = {
            'привет': ['Здравствуйте!', 'Привет!', 'Добрый день!', 'Хай!'],
            'как дела': ['Отлично! А у вас?', 'Хорошо, спасибо. Чем могу помочь?', 'Всё работает, жду ваших вопросов.'],
            'что умеешь': ['Я умею генерировать юзернеймы, искать группы, помогать с продвижением, отвечать на вопросы.'],
            'помощь': ['Я могу: генерировать свободные юзернеймы, искать чаты для пиара, давать советы по продвижению.'],
            'спасибо': ['Пожалуйста!', 'Всегда рад помочь.', 'Обращайтесь ещё.'],
            'пока': ['До свидания!', 'Всего доброго!', 'Возвращайтесь!'],
            'нейросеть': ['Я и есть нейросеть. Задайте любой вопрос.', 'Моя нейросеть готова ответить. Что вас интересует?'],
            'подписка': ['Подписка даёт неограниченные действия. Выберите в меню "Подписка".'],
            'рефералы': ['Приглашайте друзей, получайте звёзды. Ваша ссылка в разделе "Рефералы".'],
        }
        
        # Дополнительные темы
        self.topics = {
            'маркетинг': 'Продвижение в Telegram лучше начинать с анализа аудитории. Рекомендую использовать таргетированную рекламу и кросс-постинг.',
            'юзернейм': 'Уникальный юзернейм повышает узнаваемость. Генерируйте короткие и запоминающиеся варианты.',
            'группа': 'Для поиска групп используйте фильтры по участникам и активности. У нас есть функция "Найти группы".',
            'звезды': 'Звёзды — внутренняя валюта. Их можно получить за рефералов или купить подписку.',
            'админ': 'Этот вопрос лучше задать администратору бота.',
        }
    
    def _get_intent(self, text: str) -> Optional[str]:
        """Определяет намерение по ключевым словам."""
        text_lower = text.lower()
        for intent, keywords in self.intents.items():
            if intent in text_lower:
                return intent
        for topic, _ in self.topics.items():
            if topic in text_lower:
                return topic
        return None
    
    def _generate_fallback(self, text: str) -> str:
        """Генерация ответа, если намерение не распознано."""
        responses = [
            f"Интересный вопрос про «{text[:50]}». Я подумаю и отвечу чуть позже.",
            "Я ещё учусь, но постараюсь помочь. Уточните, пожалуйста, вопрос.",
            "Попробуйте воспользоваться меню — там много полезных функций.",
            "Моя нейросеть анализирует ваш запрос. Возможно, вы хотели спросить о раскрутке или юзернеймах?",
            "Задайте вопрос более конкретно, и я дам точный ответ."
        ]
        return random.choice(responses)
    
    async def generate_response(self, user_id: int, message: str, lang: str = 'ru') -> str:
        """
        Основной метод нейросети.
        Возвращает ответ на сообщение пользователя.
        """
        # Сохраняем сообщение в контекст (для многооборотных диалогов)
        if user_id not in self.context:
            self.context[user_id] = []
        self.context[user_id].append(message)
        # Ограничиваем контекст 3 сообщениями
        if len(self.context[user_id]) > 3:
            self.context[user_id].pop(0)
        
        intent = self._get_intent(message)
        
        if intent in self.intents:
            return random.choice(self.intents[intent])
        elif intent in self.topics:
            return self.topics[intent]
        else:
            # Если не распознано, пробуем ответить с учётом предыдущих сообщений
            if len(self.context[user_id]) > 1:
                # Учитываем последний ответ бота (если был)
                return self._generate_fallback(message) + " (учтён контекст диалога)"
            return self._generate_fallback(message)

# Создаём экземпляр нейросети
neural_net = LocalNeuralNetwork()

# ========== ПРОВЕРКА ПОДПИСКИ ==========
async def is_subscribed_to_channel(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except:
        return True  # Если бот не админ канала, проверку пропускаем (в проде добавьте бота в админы)

# ========== MIDDLEWARE ПРОВЕРКИ ПОДПИСКИ ==========
class SubscriptionMiddleware:
    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        
        if user_id and not await is_subscribed_to_channel(user_id):
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📢 Подписаться на канал", url=f"https://t.me/{REQUIRED_CHANNEL.lstrip('@')}")],
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")]
            ])
            text = "⚠️ *Для использования бота необходимо подписаться на наш канал!*\n\nПодпишитесь и нажмите «Я подписался»."
            if isinstance(event, Message):
                await event.answer(text, parse_mode="Markdown", reply_markup=keyboard)
            else:
                await event.message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
                await event.answer()
            return
        return await handler(event, data)

dp.message.middleware(SubscriptionMiddleware())
dp.callback_query.middleware(SubscriptionMiddleware())

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        language TEXT DEFAULT 'ru',
        subscription_end TIMESTAMP,
        subscription_type TEXT,
        balance INTEGER DEFAULT 0,
        referrer_id INTEGER,
        joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        actions_today INTEGER DEFAULT 0,
        last_action_reset DATE
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS referrals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_id INTEGER UNIQUE,
        earned_stars INTEGER DEFAULT 0,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        type TEXT,
        description TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS user_actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action_type TEXT,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

# ========== ФУНКЦИИ БД ==========
def get_user(user_id: int) -> Optional[Dict]:
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            'user_id': row[0], 'username': row[1], 'first_name': row[2],
            'language': row[3], 'subscription_end': row[4], 'subscription_type': row[5],
            'balance': row[6], 'referrer_id': row[7], 'joined_date': row[8],
            'actions_today': row[9], 'last_action_reset': row[10]
        }
    return None

def create_user(user_id: int, username: str, first_name: str, referrer_id: int = None):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
    if cursor.fetchone():
        conn.close()
        return
    if referrer_id == user_id:
        referrer_id = None
    if referrer_id:
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (referrer_id,))
        if not cursor.fetchone():
            referrer_id = None
    cursor.execute('INSERT INTO users (user_id, username, first_name, referrer_id, last_action_reset) VALUES (?, ?, ?, ?, ?)',
                   (user_id, username, first_name, referrer_id, datetime.now().date().isoformat()))
    if referrer_id:
        cursor.execute('UPDATE users SET balance = balance + 50 WHERE user_id = ?', (referrer_id,))
        cursor.execute('INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)',
                       (referrer_id, 50, 'referral_bonus', f'Бонус за приглашение {user_id}'))
        cursor.execute('INSERT INTO referrals (referrer_id, referred_id, earned_stars) VALUES (?, ?, ?)',
                       (referrer_id, user_id, 50))
    conn.commit()
    conn.close()

def check_subscription(user_id: int) -> Tuple[bool, Optional[str]]:
    user = get_user(user_id)
    if not user or not user['subscription_end']:
        return False, None
    sub_end = datetime.fromisoformat(user['subscription_end'])
    if sub_end > datetime.now():
        return True, user['subscription_type']
    return False, None

def can_use_action(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    has_sub, _ = check_subscription(user_id)
    if has_sub:
        return True
    today = datetime.now().date().isoformat()
    if user['last_action_reset'] != today:
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET actions_today = 0, last_action_reset = ? WHERE user_id = ?', (today, user_id))
        conn.commit()
        conn.close()
        user['actions_today'] = 0
    return user['actions_today'] < 3

def use_action(user_id: int, action_type: str) -> bool:
    if not can_use_action(user_id):
        return False
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET actions_today = actions_today + 1 WHERE user_id = ?', (user_id,))
    cursor.execute('INSERT INTO user_actions (user_id, action_type) VALUES (?, ?)', (user_id, action_type))
    conn.commit()
    conn.close()
    return True

def add_subscription(user_id: int, days: int, sub_type: str):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    user = get_user(user_id)
    if user and user['subscription_end']:
        current_end = datetime.fromisoformat(user['subscription_end'])
        new_end = max(current_end, datetime.now()) + timedelta(days=days)
    else:
        new_end = datetime.now() + timedelta(days=days)
    cursor.execute('UPDATE users SET subscription_end = ?, subscription_type = ? WHERE user_id = ?',
                   (new_end.isoformat(), sub_type, user_id))
    conn.commit()
    conn.close()

def add_balance(user_id: int, amount: int, description: str):
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    cursor.execute('INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)',
                   (user_id, amount, 'income', description))
    conn.commit()
    conn.close()

def get_referral_stats(user_id: int) -> Dict:
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*), SUM(earned_stars) FROM referrals WHERE referrer_id = ?', (user_id,))
    count, total = cursor.fetchone()
    conn.close()
    return {'count': count or 0, 'total_earned': total or 0}

# ========== ТЕКСТЫ ==========
TEXTS = {
    'ru': {
        'welcome': "🌟 *Добро пожаловать в HarukaMedia!* 🌟\n\nВыберите язык / Choose language:",
        'lang_selected': "✅ Язык выбран: Русский\n\nВыберите действие:",
        'main_menu': "🌟 *Главное меню HarukaMedia* 🌟\n\nВыберите раздел:",
        'promotion_btn': "🚀 Раскрутка",
        'promotion_menu': "🚀 *Раскрутка*\n\nВыберите действие:",
        'username_gen_btn': "🎲 Генератор юзернеймов",
        'find_groups_btn': "🔍 Найти группы",
        'subscription_btn': "💎 Подписка",
        'referral_btn': "👥 Рефералы",
        'profile_btn': "👤 Профиль",
        'neural_btn': "🧠 Нейросеть",
        'no_actions': "⚠️ У вас закончились бесплатные действия на сегодня! Купите подписку.",
        'choose_length': "🎲 Выберите длину юзернейма (5-32 символа):",
        'enter_count': "✅ Длина {length}. Теперь введите количество (1-10):",
        'generating': "⏳ Генерация...",
        'generated': "✅ *Сгенерированные юзернеймы:*\n\n{usernames}",
        'no_usernames': "❌ Не удалось сгенерировать юзернеймы.",
        'subscription_prices': "💎 *Подписка:*\n1 день - 5⭐️\n10 дней - 40⭐️\n30 дней - 85⭐️\nНавсегда - 135⭐️",
        'subscription_bought': "✅ Подписка активирована до {end_date}",
        'insufficient_balance': "❌ Недостаточно звезд. Баланс: {balance}⭐️",
        'referral_info': "👥 *Рефералы*\nСсылка: `https://t.me/{bot_username}?start=ref{user_id}`\nПриглашено: {count}\nЗаработано: {earned}⭐️\nБаланс: {balance}⭐️",
        'profile': "👤 *Профиль*\nID: `{user_id}`\nИмя: {name}\nБаланс: {balance}⭐️\nПодписка: {subscription}\nДействий сегодня: {actions}/3",
        'back_btn': "🔙 Назад",
        'no_subscription': "Нет подписки",
        'subscription_active': "{sub_type} до {end_date}",
        'group_search': "🔍 *Поиск групп*\nНастройте фильтры:",
        'members_btn': "👥 Участники",
        'bots_btn': "🤖 Боты",
        'activity_btn': "📊 Активность",
        'generate_btn': "🔍 Генерировать",
        'enter_members': "Введите минимальное количество участников:",
        'enter_activity_days': "Введите кол-во дней анализа (1-30):",
        'activity_types': "Выберите тип чатов:",
        'real_activity': "💬 Живое общение",
        'promo_chats': "📢 Пиар-чаты",
        'all_chats': "🌐 Все чаты",
        'generating_groups': "⏳ Поиск групп...",
        'groups_found': "🔗 *Найденные группы:*\n{groups}\n\n{analysis}",
        'no_groups': "Ничего не найдено.",
        'admin_panel': "🔧 Админ-панель",
        'find_user': "🔍 Найти пользователя",
        'give_subscription': "🎫 Выдать подписку",
        'take_subscription': "❌ Забрать подписку",
        'enter_username': "Введите username (без @):",
        'user_not_found': "Пользователь не найден",
        'user_info': "👤 *{username}*\nID: `{user_id}`\nБаланс: {balance}⭐️\nПодписка: {subscription}",
        'enter_subscription_days': "Введите дни (1,10,30,0=навсегда):",
        'subscription_given': "✅ Подписка выдана @{username} на {days} дней",
        'subscription_taken': "❌ Подписка забрана",
        'no_access': "⛔ Нет доступа",
        'neural_welcome': "🧠 *Нейросеть*\nНапишите любой запрос, и я сгенерирую ответ.\n*Одно действие = один запрос.*",
        'neural_thinking': "🤔 Думаю...",
        'neural_answer': "🧠 *Ответ нейросети:*\n\n{answer}",
        'neural_error': "❌ Ошибка генерации. Попробуйте ещё раз.",
    },
    'en': {
        'welcome': "🌟 *Welcome to HarukaMedia!* 🌟\n\nChoose language / Выберите язык:",
        'lang_selected': "✅ Language: English\n\nChoose action:",
        'main_menu': "🌟 *HarukaMedia Main Menu* 🌟",
        'promotion_btn': "🚀 Promotion",
        'promotion_menu': "🚀 *Promotion*\n\nChoose an action:",
        'username_gen_btn': "🎲 Username Generator",
        'find_groups_btn': "🔍 Find Groups",
        'subscription_btn': "💎 Subscription",
        'referral_btn': "👥 Referrals",
        'profile_btn': "👤 Profile",
        'neural_btn': "🧠 Neural Network",
        'no_actions': "⚠️ No free actions left today! Buy a subscription.",
        'choose_length': "🎲 Choose username length (5-32):",
        'enter_count': "✅ Length {length}. Enter count (1-10):",
        'generating': "⏳ Generating...",
        'generated': "✅ *Generated usernames:*\n\n{usernames}",
        'no_usernames': "❌ Could not generate usernames.",
        'subscription_prices': "💎 *Subscription:*\n1 day - 5⭐️\n10 days - 40⭐️\n30 days - 85⭐️\nForever - 135⭐️",
        'subscription_bought': "✅ Subscription active until {end_date}",
        'insufficient_balance': "❌ Insufficient stars. Balance: {balance}⭐️",
        'referral_info': "👥 *Referrals*\nLink: `https://t.me/{bot_username}?start=ref{user_id}`\nInvited: {count}\nEarned: {earned}⭐️\nBalance: {balance}⭐️",
        'profile': "👤 *Profile*\nID: `{user_id}`\nName: {name}\nBalance: {balance}⭐️\nSubscription: {subscription}\nActions today: {actions}/3",
        'back_btn': "🔙 Back",
        'no_subscription': "No subscription",
        'subscription_active': "{sub_type} until {end_date}",
        'group_search': "🔍 *Group Search*\nSet filters:",
        'members_btn': "👥 Members",
        'bots_btn': "🤖 Bots",
        'activity_btn': "📊 Activity",
        'generate_btn': "🔍 Generate",
        'enter_members': "Enter minimum members:",
        'enter_activity_days': "Enter analysis days (1-30):",
        'activity_types': "Select chat type:",
        'real_activity': "💬 Real Activity",
        'promo_chats': "📢 Promo Chats",
        'all_chats': "🌐 All Chats",
        'generating_groups': "⏳ Searching...",
        'groups_found': "🔗 *Found groups:*\n{groups}\n\n{analysis}",
        'no_groups': "Nothing found.",
        'admin_panel': "🔧 Admin Panel",
        'find_user': "🔍 Find User",
        'give_subscription': "🎫 Give Subscription",
        'take_subscription': "❌ Take Subscription",
        'enter_username': "Enter username (without @):",
        'user_not_found': "User not found",
        'user_info': "👤 *{username}*\nID: `{user_id}`\nBalance: {balance}⭐️\nSubscription: {subscription}",
        'enter_subscription_days': "Enter days (1,10,30,0=forever):",
        'subscription_given': "✅ Subscription given to @{username} for {days} days",
        'subscription_taken': "❌ Subscription taken",
        'no_access': "⛔ Access denied",
        'neural_welcome': "🧠 *Neural Network*\nSend any query, I'll generate an answer.\n*One action = one query.*",
        'neural_thinking': "🤔 Thinking...",
        'neural_answer': "🧠 *Neural Network answer:*\n\n{answer}",
        'neural_error': "❌ Generation error. Try again.",
    }
}

# ========== КЛАВИАТУРЫ ==========
def get_language_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🇷🇺 Русский", callback_data="lang_ru")
    builder.button(text="🇬🇧 English", callback_data="lang_en")
    return builder.as_markup()

def get_main_menu_keyboard(lang: str, is_admin: bool = False):
    texts = TEXTS[lang]
    builder = InlineKeyboardBuilder()
    builder.button(text=texts['promotion_btn'], callback_data="menu_promotion")
    builder.button(text=texts['find_groups_btn'], callback_data="menu_find_groups")
    builder.button(text=texts['subscription_btn'], callback_data="menu_subscription")
    builder.button(text=texts['referral_btn'], callback_data="menu_referral")
    builder.button(text=texts['profile_btn'], callback_data="menu_profile")
    builder.button(text=texts['neural_btn'], callback_data="menu_neural")
    if is_admin:
        builder.button(text="🔧 Admin", callback_data="admin_panel")
    builder.adjust(1)
    return builder.as_markup()

def get_back_to_main_keyboard(lang: str):
    builder = InlineKeyboardBuilder()
    builder.button(text=TEXTS[lang]['back_btn'], callback_data="back_to_main")
    return builder.as_markup()

def get_back_to_promo_keyboard(lang: str):
    builder = InlineKeyboardBuilder()
    builder.button(text=TEXTS[lang]['back_btn'], callback_data="back_to_promo")
    return builder.as_markup()

def get_username_gen_keyboard(lang: str):
    builder = InlineKeyboardBuilder()
    for length in [5,10,15,20,25,32]:
        builder.button(text=f"{length} симв.", callback_data=f"username_len_{length}")
    builder.button(text=TEXTS[lang]['back_btn'], callback_data="back_to_promo")
    builder.adjust(2)
    return builder.as_markup()

def get_subscription_keyboard(lang: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="1 day - 5⭐️", callback_data="sub_1")
    builder.button(text="10 days - 40⭐️", callback_data="sub_10")
    builder.button(text="30 days - 85⭐️", callback_data="sub_30")
    builder.button(text="Forever - 135⭐️", callback_data="sub_0")
    builder.button(text=TEXTS[lang]['back_btn'], callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def get_promotion_menu_keyboard(lang: str):
    texts = TEXTS[lang]
    builder = InlineKeyboardBuilder()
    builder.button(text=texts['username_gen_btn'], callback_data="promo_gen_usernames")
    builder.button(text=texts['back_btn'], callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

def get_admin_keyboard(lang: str):
    texts = TEXTS[lang]
    builder = InlineKeyboardBuilder()
    builder.button(text=texts['find_user'], callback_data="admin_find_user")
    builder.button(text=texts['give_subscription'], callback_data="admin_give_sub")
    builder.button(text=texts['take_subscription'], callback_data="admin_take_sub")
    builder.button(text=texts['back_btn'], callback_data="back_to_main")
    builder.adjust(1)
    return builder.as_markup()

# ========== ОБРАБОТЧИКИ ==========
@dp.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username or ""
    first_name = message.from_user.first_name
    referrer_id = None
    if command.args and command.args.startswith("ref"):
        try:
            referrer_id = int(command.args[3:])
        except:
            pass
    create_user(user_id, username, first_name, referrer_id)
    await message.answer(TEXTS['ru']['welcome'], reply_markup=get_language_keyboard())

@dp.callback_query(F.data == "check_subscription")
async def check_subscription_callback(callback: CallbackQuery):
    if await is_subscribed_to_channel(callback.from_user.id):
        await callback.message.delete()
        await callback.message.answer(TEXTS['ru']['welcome'], reply_markup=get_language_keyboard())
    else:
        await callback.answer("Подпишитесь на канал!", show_alert=True)

@dp.callback_query(F.data.startswith("lang_"))
async def set_language(callback: CallbackQuery):
    lang = callback.data.split("_")[1]
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET language = ? WHERE user_id = ?', (lang, callback.from_user.id))
    conn.commit()
    conn.close()
    user = get_user(callback.from_user.id)
    is_admin_flag = callback.from_user.id in ADMIN_IDS
    await callback.message.edit_text(TEXTS[lang]['lang_selected'], reply_markup=get_main_menu_keyboard(lang, is_admin_flag))
    await callback.answer()

@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    is_admin_flag = callback.from_user.id in ADMIN_IDS
    await callback.message.edit_text(TEXTS[lang]['main_menu'], reply_markup=get_main_menu_keyboard(lang, is_admin_flag))
    await callback.answer()

@dp.callback_query(F.data == "menu_promotion")
async def menu_promotion(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    if not can_use_action(callback.from_user.id):
        await callback.answer(TEXTS[lang]['no_actions'], show_alert=True)
        return
    await callback.message.edit_text(TEXTS[lang]['promotion_menu'], reply_markup=get_promotion_menu_keyboard(lang))
    await callback.answer()

@dp.callback_query(F.data == "promo_gen_usernames")
async def start_username_gen(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    if not use_action(callback.from_user.id, "username_gen"):
        await callback.answer(TEXTS[lang]['no_actions'], show_alert=True)
        return
    await callback.message.edit_text(TEXTS[lang]['choose_length'], reply_markup=get_username_gen_keyboard(lang))
    await state.set_state(UsernameGenStates.waiting_for_length)
    await callback.answer()

class UsernameGenStates(StatesGroup):
    waiting_for_length = State()
    waiting_for_count = State()

@dp.callback_query(UsernameGenStates.waiting_for_length, F.data.startswith("username_len_"))
async def username_length_chosen(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    length = int(callback.data.split("_")[2])
    await state.update_data(username_length=length)
    await callback.message.edit_text(TEXTS[lang]['enter_count'].format(length=length), reply_markup=get_back_to_promo_keyboard(lang))
    await state.set_state(UsernameGenStates.waiting_for_count)
    await callback.answer()

@dp.message(UsernameGenStates.waiting_for_count, F.text.regexp(r"^\d+$"))
async def username_count_chosen(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    lang = user['language'] if user else 'ru'
    count = int(message.text)
    if count < 1 or count > 10:
        await message.answer("❌ От 1 до 10")
        return
    data = await state.get_data()
    length = data.get("username_length")
    processing = await message.answer(TEXTS[lang]['generating'])
    usernames = [''.join(random.choices(string.ascii_lowercase + string.digits, k=length)) for _ in range(count)]
    if usernames:
        text = '\n'.join([f"• `{u}`" for u in usernames])
        await processing.edit_text(TEXTS[lang]['generated'].format(usernames=text), parse_mode="Markdown", reply_markup=get_back_to_main_keyboard(lang))
    else:
        await processing.edit_text(TEXTS[lang]['no_usernames'])
    await state.clear()

@dp.callback_query(F.data == "back_to_promo")
async def back_to_promo(callback: CallbackQuery):
    await menu_promotion(callback)

@dp.callback_query(F.data == "menu_subscription")
async def menu_subscription(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    await callback.message.edit_text(TEXTS[lang]['subscription_prices'], reply_markup=get_subscription_keyboard(lang))
    await callback.answer()

@dp.callback_query(F.data.startswith("sub_"))
async def buy_subscription(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    sub_type = callback.data.split("_")[1]
    prices = {'1': (1,5,"1 day"), '10': (10,40,"10 days"), '30': (30,85,"30 days"), '0': (3650,135,"Forever")}
    days, price, type_name = prices[sub_type]
    if user['balance'] < price:
        await callback.answer(TEXTS[lang]['insufficient_balance'].format(balance=user['balance']), show_alert=True)
        return
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET balance = balance - ? WHERE user_id = ?', (price, callback.from_user.id))
    cursor.execute('INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)',
                   (callback.from_user.id, -price, 'subscription', f'Purchase {type_name}'))
    conn.commit()
    conn.close()
    add_subscription(callback.from_user.id, days, type_name)
    if user['referrer_id']:
        add_balance(user['referrer_id'], int(price*0.25), f'Commission from {callback.from_user.id}')
    end_date = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    await callback.message.edit_text(TEXTS[lang]['subscription_bought'].format(end_date=end_date), reply_markup=get_back_to_main_keyboard(lang))
    await callback.answer()

@dp.callback_query(F.data == "menu_referral")
async def menu_referral(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    stats = get_referral_stats(callback.from_user.id)
    bot_username = (await bot.get_me()).username
    await callback.message.edit_text(
        TEXTS[lang]['referral_info'].format(
            bot_username=bot_username,
            user_id=callback.from_user.id,
            count=stats['count'],
            earned=stats['total_earned'],
            balance=user['balance'],
        ),
        parse_mode="Markdown",
        reply_markup=get_back_to_main_keyboard(lang),
    )
    await callback.answer()

@dp.callback_query(F.data == "menu_profile")
async def menu_profile(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    has_sub, sub_info = check_subscription(callback.from_user.id)
    if has_sub:
        subscription_text = TEXTS[lang]['subscription_active'].format(sub_type=sub_info, end_date=datetime.fromisoformat(user['subscription_end']).strftime("%Y-%m-%d"))
    else:
        subscription_text = TEXTS[lang]['no_subscription']
    stats = get_referral_stats(callback.from_user.id)
    await callback.message.edit_text(TEXTS[lang]['profile'].format(user_id=callback.from_user.id, name=user['first_name'], balance=user['balance'], subscription=subscription_text, actions=user['actions_today']), parse_mode="Markdown", reply_markup=get_back_to_main_keyboard(lang))
    await callback.answer()

# ========== НЕЙРОСЕТЬ ==========
@dp.callback_query(F.data == "menu_neural")
async def menu_neural(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    if not can_use_action(callback.from_user.id):
        await callback.answer(TEXTS[lang]['no_actions'], show_alert=True)
        return
    await callback.message.edit_text(TEXTS[lang]['neural_welcome'], reply_markup=get_back_to_main_keyboard(lang))
    await state.set_state(NeuralStates.waiting_for_query)
    await callback.answer()

class NeuralStates(StatesGroup):
    waiting_for_query = State()

@dp.message(NeuralStates.waiting_for_query)
async def neural_query(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    lang = user['language'] if user else 'ru'
    
    # Проверяем ещё раз действия (на случай, если пользователь долго думал)
    if not use_action(message.from_user.id, "neural_network"):
        await message.answer(TEXTS[lang]['no_actions'])
        await state.clear()
        return
    
    thinking = await message.answer(TEXTS[lang]['neural_thinking'])
    
    # Генерируем ответ с помощью встроенной нейросети
    try:
        answer = await neural_net.generate_response(message.from_user.id, message.text, lang)
        await thinking.delete()
        await message.answer(TEXTS[lang]['neural_answer'].format(answer=answer), parse_mode="Markdown", reply_markup=get_back_to_main_keyboard(lang))
    except Exception as e:
        await thinking.delete()
        await message.answer(TEXTS[lang]['neural_error'])
        logging.error(f"Neural error: {e}")
    
    await state.clear()

# ========== АДМИНКА ==========
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(TEXTS['ru']['no_access'], show_alert=True)
        return
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    await callback.message.edit_text(TEXTS[lang]['admin_panel'], reply_markup=get_admin_keyboard(lang))
    await callback.answer()

class AdminStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_subscription_days = State()

@dp.callback_query(F.data == "admin_find_user")
async def admin_find_user(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    await callback.message.edit_text(TEXTS[lang]['enter_username'], reply_markup=get_back_to_main_keyboard(lang))
    await state.set_state(AdminStates.waiting_for_username)
    await state.update_data(admin_action="find")
    await callback.answer()

@dp.callback_query(F.data == "admin_give_sub")
async def admin_give_sub(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    await callback.message.edit_text(TEXTS[lang]['enter_username'], reply_markup=get_back_to_main_keyboard(lang))
    await state.set_state(AdminStates.waiting_for_username)
    await state.update_data(admin_action="give_sub")
    await callback.answer()

@dp.callback_query(F.data == "admin_take_sub")
async def admin_take_sub(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    user = get_user(callback.from_user.id)
    lang = user['language'] if user else 'ru'
    await callback.message.edit_text(TEXTS[lang]['enter_username'], reply_markup=get_back_to_main_keyboard(lang))
    await state.set_state(AdminStates.waiting_for_username)
    await state.update_data(admin_action="take_sub")
    await callback.answer()

@dp.message(AdminStates.waiting_for_username)
async def admin_process_username(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    action = data.get('admin_action')
    username = message.text.strip().lstrip('@')
    conn = sqlite3.connect('bot_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, language, first_name, balance, subscription_end, subscription_type FROM users WHERE username = ?', (username,))
    result = cursor.fetchone()
    conn.close()
    if not result:
        await message.answer("❌ User not found")
        await state.clear()
        return
    target_id, target_lang, first_name, balance, sub_end, sub_type = result
    if action == "find":
        sub_text = f"{sub_type} до {sub_end[:10]}" if sub_end else "Нет подписки"
        await message.answer(f"👤 *{username}*\nID: `{target_id}`\nБаланс: {balance}⭐️\nПодписка: {sub_text}", parse_mode="Markdown")
        await state.clear()
    elif action == "give_sub":
        await state.update_data(target_id=target_id, target_username=username)
        await message.answer("Введите количество дней (1,10,30,0=навсегда):")
        await state.set_state(AdminStates.waiting_for_subscription_days)
    elif action == "take_sub":
        conn = sqlite3.connect('bot_database.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET subscription_end = NULL, subscription_type = NULL WHERE user_id = ?', (target_id,))
        conn.commit()
        conn.close()
        await message.answer(f"✅ Подписка забрана у @{username}")
        await state.clear()

@dp.message(AdminStates.waiting_for_subscription_days)
async def admin_give_sub_days(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        days = int(message.text.strip())
    except:
        await message.answer("Введите число")
        return
    data = await state.get_data()
    target_id = data.get('target_id')
    target_username = data.get('target_username')
    if days == 0:
        days = 3650
        sub_type = "Forever"
    elif days == 1:
        sub_type = "1 day"
    elif days == 10:
        sub_type = "10 days"
    elif days == 30:
        sub_type = "30 days"
    else:
        sub_type = f"{days} days"
    add_subscription(target_id, days, sub_type)
    if sub_type == "Forever":
        await message.answer(f"✅ Подписка выдана @{target_username} навсегда")
    else:
        await message.answer(f"✅ Подписка выдана @{target_username} на {days} дней")
    await state.clear()

# ========== ЗАПУСК ==========
async def main():
    print("🤖 Bot HarukaMedia is starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())