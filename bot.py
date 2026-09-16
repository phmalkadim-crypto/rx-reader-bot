import os
import sqlite3
import time
from datetime import datetime, timedelta
import google.generativeai as genai
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# جلب التوكن حصراً من بيئة العمل في Render
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

# جلب مفاتيح Gemini حصراً من متغيرات البيئة بدون أي قيم وهمية
GEMINI_API_KEYS = []
for i in range(1, 11):
    key = os.environ.get(f"GEMINI_KEY_{i}")
    if key:
        GEMINI_API_KEYS.append(key)

# إذا ماكو ولا مفتاح مضاف بالبيئة، ننبهك
if not GEMINI_API_KEYS:
    print("⚠️ تنبيه: لم يتم العثور على أي مفتاح Gemini في متغيرات البيئة!")

ADMIN_ID = 569170097
REQUIRED_CHANNEL = "@Saydlogy"
ADMIN_USERNAME = "MPh_70"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
admin_states = {}
current_key_index = 0

def get_next_key():
    global current_key_index
    if not GEMINI_API_KEYS:
        raise Exception("لا توجد مفاتيح Gemini مضافة في Environment!")
    key = GEMINI_API_KEYS[current_key_index]
    current_key_index = (current_key_index + 1) % len(GEMINI_API_KEYS)
    return key

def generate_content_with_retry(image_path, prompt):
    attempts = len(GEMINI_API_KEYS)
    if attempts == 0:
        raise Exception("الرجاء إضافة مفاتيح Gemini في Environment Variables على Render.")
        
    last_exception = None

    for _ in range(attempts):
        key = get_next_key()
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel('gemini-2.5-flash')
            
            sample_file = genai.upload_file(image_path)
            response = model.generate_content([sample_file, prompt])
            return response.text
        except Exception as e:
            last_exception = e
            continue
            
    raise last_exception

def init_db():
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            free_tries INTEGER DEFAULT 5,
            subscription_expiry TEXT,
            subscription_start TEXT,
            username TEXT,
            full_name TEXT
        )
    ''')
    conn.commit()
    
    cursor.execute("PRAGMA table_info(users)")
    columns = [col[1] for col in cursor.fetchall()]
    if "username" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
    if "full_name" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
    conn.commit()
    conn.close()

init_db()

def get_user(user_id, username=None, full_name=None):
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT free_tries, subscription_expiry FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute('INSERT OR IGNORE INTO users (user_id, free_tries, username, full_name) VALUES (?, 5, ?, ?)', 
                       (user_id, username, full_name))
        conn.commit()
        row = (5, None)
        
        try:
            u_name = f"@{username}" if username else "بدون معرف"
            f_name = full_name if full_name else "بدون اسم"
            notification = (
                "👤 **مستخدم جديد دخل للبوت!**\n\n"
                f"▫️ الاسم: {f_name}\n"
                f"▫️ المعرف: {u_name}\n"
                f"▫️ الـ ID: `{user_id}`"
            )
            bot.send_message(ADMIN_ID, notification, parse_mode="Markdown")
        except Exception:
            pass
    conn.close()
    return row

def update_free_tries(user_id, tries):
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET free_tries = ? WHERE user_id = ?', (tries, user_id))
    conn.commit()
    conn.close()

def add_subscription_days(user_id, days):
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT subscription_expiry, subscription_start FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    now = datetime.now()
    base_date = now
    start_str = now.strftime('%Y-%m-%d %H:%M:%S')
    
    if row and row[0]:
        try:
            expiry_date = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
            if expiry_date > now:
                base_date = expiry_date
                if row[1]:
                    start_str = row[1]
        except Exception:
            pass
            
    new_expiry = base_date + timedelta(days=days)
    expiry_str = new_expiry.strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute('UPDATE users SET subscription_expiry = ?, subscription_start = ? WHERE user_id = ?', (expiry_str, start_str, user_id))
    conn.commit()
    conn.close()
    return start_str, expiry_str

def check_subscription(user_id):
    if user_id == ADMIN_ID:
        return True
    try:
        member = bot.get_chat_member(REQUIRED_CHANNEL, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        else:
            return False
    except Exception as e:
        return False

def get_channel_keyboard():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📢 اشترك في القناة الآن", url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}"))
    markup.add(InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_channel_sub"))
    return markup

def get_vip_status_keyboard():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📊 حالة اشتراكي", callback_data="check_my_vip_status"))
    return markup

def get_contact_admin_keyboard():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💬 تواصل مع المدير لتفعيل الاشتراك", url=f"https://t.me/{ADMIN_USERNAME}"))
    return markup

def get_admin_reply_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(KeyboardButton("تفعيل الأشتراك"), KeyboardButton("start - ابدأ"))
    markup.row(KeyboardButton("احصائيات البوت"), KeyboardButton("الإذاعة"))
    markup.row(KeyboardButton("تعويض"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = message.from_user
    get_user(user.id, user.username, user.first_name)
    
    if user.id == ADMIN_ID:
        bot.reply_to(message, "أهلاً بك يا مدير البوت 👑", reply_markup=get_admin_reply_keyboard())
    else:
        if not check_subscription(user.id):
            sub_warning = (
                "⚠️ **عذراً، يجب عليك الاشتراك في قناة البوت أولاً لتتمكن من استخدامه!**\n\n"
                f"يرجى الانضمام إلى القناة: {REQUIRED_CHANNEL}\n"
                "بعد الانضمام، اضغط على زر (تحقق من الاشتراك) أدناه 👇"
            )
            bot.reply_to(message, sub_warning, parse_mode="Markdown", reply_markup=get_channel_keyboard())
            return
        bot.reply_to(message, "أهلاً بك! أرسل لي صورة الوصفة الطبية وسأقوم بقراءتها فوراً.")

@bot.callback_query_handler(func=lambda call: call.data == "check_channel_sub")
def callback_check_channel(call):
    user_id = call.from_user.id
    if check_subscription(user_id):
        bot.answer_callback_query(call.id, "✅ تم التحقق من اشتراكك بنجاح!")
        try:
            bot.edit_message_text(
                "✅ شكراً لاشتراكك في القناة! أرسل لي صورة الوصفة الطبية الآن 📄",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        except Exception:
            bot.send_message(user_id, "✅ شكراً لاشتراكك! أرسل صورة الوصفة الآن.")
    else:
        bot.answer_callback_query(call.id, "⚠️ عذراً، أنت لست مشتركاً في القناة!", show_alert=True)

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and message.text in [
    "تفعيل الأشتراك", "start - ابدأ", "احصائيات البوت", "الإذاعة", "تعويض"
])
def handle_admin_reply_buttons(message):
    text = message.text
    if text == "تفعيل الأشتراك":
        admin_states[ADMIN_ID] = {"action": "waiting_activate_id"}
        bot.send_message(ADMIN_ID, "✍️ أرسل آيدي المستخدم (ID) المراد تفعيل اشتراكه:", parse_mode="Markdown")
    elif text == "start - ابدأ":
        bot.reply_to(message, "أهلاً بك مجدداً يا مدير البوت 👑", reply_markup=get_admin_reply_keyboard())
    elif text == "احصائيات البوت":
        show_stats()
    elif text == "الإذاعة":
        admin_states[ADMIN_ID] = {"action": "waiting_broadcast_text"}
        bot.send_message(ADMIN_ID, "📢 أرسل النص الذي تريد إذاعته:", parse_mode="Markdown")
    elif text == "تعويض":
        admin_states[ADMIN_ID] = {"action": "waiting_compensate_id"}
        bot.send_message(ADMIN_ID, "🎁 أرسل آيدي المستخدم المراد تعويضه:", parse_mode="Markdown")

def show_stats():
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    cursor.execute('SELECT subscription_expiry FROM users')
    all_subs = cursor.fetchall()
    active_vips = 0
    now = datetime.now()
    for row in all_subs:
        if row[0]:
            try:
                if datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S') > now:
                    active_vips += 1
            except Exception:
                pass
    conn.close()
    stats_msg = f"📈 إحصائيات البوت:\n\n👥 إجمالي المستخدمين: {total_users}\n⭐ المشتركين (VIP): {active_vips}\n🆓 المجانيين: {total_users - active_vips}"
    bot.send_message(ADMIN_ID, stats_msg, parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())

@bot.message_handler(func=lambda message: message.from_user.id == ADMIN_ID and ADMIN_ID in admin_states)
def handle_admin_input(message):
    state = admin_states[ADMIN_ID].get("action")
    if state == "waiting_activate_id":
        try:
            target_id = int(message.text.strip())
            start_str, expiry_str = add_subscription_days(target_id, 30)
            bot.reply_to(message, f"✅ تم التفعيل لمدة شهر لـ `{target_id}`", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
            bot.send_message(target_id, "🎉 مبارك! تم تفعيل اشتراكك الشهري بنجاح.", reply_markup=get_vip_status_keyboard())
        except ValueError:
            bot.reply_to(message, "⚠️ الآيدي يجب أن يكون أرقاماً فقط.")
        finally:
            del admin_states[ADMIN_ID]
    elif state == "waiting_broadcast_text":
        text_to_send = message.text.strip()
        conn = sqlite3.connect('users.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users')
        users = cursor.fetchall()
        conn.close()
        for u in users:
            if u[0] != ADMIN_ID:
                try:
                    bot.send_message(u[0], text_to_send, parse_mode="Markdown")
                except Exception:
                    pass
        bot.reply_to(message, "✅ تمت الإذاعة بنجاح!", reply_markup=get_admin_reply_keyboard())
        del admin_states[ADMIN_ID]
    elif state == "waiting_compensate_id":
        try:
            target_id = int(message.text.strip())
            admin_states[ADMIN_ID] = {"action": "waiting_compensate_days", "target_id": target_id}
            bot.reply_to(message, "⏳ أرسل عدد الأيام المراد تعويضه بها:", parse_mode="Markdown")
        except ValueError:
            bot.reply_to(message, "⚠️ الآيدي يجب أن يكون أرقاماً.")
            del admin_states[ADMIN_ID]
    elif state == "waiting_compensate_days":
        try:
            days = int(message.text.strip())
            target_id = admin_states[ADMIN_ID].get("target_id")
            start_str, expiry_str = add_subscription_days(target_id, days)
            bot.reply_to(message, f"🎁 تم التعويض بـ {days} أيام بنجاح!", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
            bot.send_message(target_id, f"🎁 تمت إضافة رصيد تعويض بقيمة {days} أيام!", reply_markup=get_vip_status_keyboard())
        except ValueError:
            bot.reply_to(message, "⚠️ الأيام يجب أن تكون أرقاماً.")
        finally:
            del admin_states[ADMIN_ID]

@bot.callback_query_handler(func=lambda call: call.data == "check_my_vip_status")
def callback_check_vip_status(call):
    user_id = call.from_user.id
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT subscription_start, subscription_expiry FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    bot.answer_callback_query(call.id)
    if not row or not row[1]:
        bot.send_message(user_id, "⚠️ ليس لديك اشتراك نشط حالياً.")
        return
    start_str, expiry_str = row[0], row[1]
    try:
        expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return
    now = datetime.now()
    if expiry_date <= now:
        bot.send_message(user_id, "⚠️ عذراً، انتهت صلاحية اشتراكك.")
        return
    remaining_days = (expiry_date - now).days
    status_msg = f"⭐ تفاصيل اشتراكك:\n\n📅 البدء: `{start_str}`\n⏳ الانتهاء: `{expiry_str}`\n⏱️ الباقي: `~{remaining_days} يوم`\n\nتواصل مع المدير: [{ADMIN_USERNAME}](https://t.me/{ADMIN_USERNAME})"
    bot.send_message(user_id, status_msg, parse_mode="Markdown", reply_markup=get_vip_status_keyboard())

@bot.message_handler(content_types=['photo'])
def handle_prescription(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        if not check_subscription(user_id):
            bot.reply_to(message, f"⚠️ يجب الاشتراك في قناة البوت أولاً: {REQUIRED_CHANNEL}", reply_markup=get_channel_keyboard())
            return
        free_tries, expiry_str = get_user(user_id, message.from_user.username, message.from_user.first_name)
        is_vip = False
        if expiry_str:
            try:
                if datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S') > datetime.now():
                    is_vip = True
            except Exception:
                pass
        if not is_vip and free_tries <= 0:
            sub_text = f"⚠️ انتهت محاولاتك المجانية (5 محاولات)!\n\nللاشتراك الشهري بقيمة 5,000 د.ع تواصل معنا.\nالآيدي الخاص بك: `{user_id}`"
            bot.reply_to(message, sub_text, parse_mode="Markdown", reply_markup=get_contact_admin_keyboard())
            return
    else:
        is_vip = True

    msg = bot.reply_to(message, "⏳ جاري قراءة الوصفة الطبية...")
    image_path = f"prescription_{user_id}_{message.message_id}.jpg"
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open(image_path, 'wb') as new_file:
            new_file.write(downloaded_file)
        prompt = "اقرأ هذه الوصفة الطبية بدقة واستخرج اسم العلاج مع الجرعة بدون نجوم (**) أو تنسيق Markdown، واختم بإخلاء المسؤولية."
        result_text = generate_content_with_retry(image_path, prompt)
        bot.edit_message_text(result_text, chat_id=message.chat.id, message_id=msg.message_id)
        if user_id != ADMIN_ID and not is_vip:
            free_tries, _ = get_user(user_id)
            update_free_tries(user_id, max(0, free_tries - 1))
    except Exception as e:
        bot.edit_message_text(f"عذراً، حدث خطأ: {str(e)}", chat_id=message.chat.id, message_id=msg.message_id)
    finally:
        if os.path.exists(image_path):
            os.remove(image_path)

print("Bot is running...")
while True:
    try:
        bot.polling(non_stop=True, timeout=60, long_polling_timeout=60)
    except Exception as e:
        time.sleep(5)
