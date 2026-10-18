import os
import sqlite3
import time
from datetime import datetime, timedelta
from google import genai
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telebot import apihelper

TELEGRAM_BOT_TOKEN = "8868728973:AAGahNwax7cvbyri7-Fy_Guskclq995Dewo"
DEFAULT_ADMIN_ID = 569170097

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
admin_states = {}
current_key_index = 0

def init_db():
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            free_tries INTEGER DEFAULT 3,
            subscription_expiry TEXT,
            subscription_start TEXT,
            username TEXT,
            full_name TEXT,
            is_banned INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_value TEXT UNIQUE
        )
    ''')
    conn.commit()
    
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('sub_price', '3,000 د.ع')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('free_tries_limit', '3')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('admin_username', 'MPh_70')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('required_channel', '@Saydlogy')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('ai_model', 'gemini-2.5-flash')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('admin_id', ?)", (str(DEFAULT_ADMIN_ID),))
    
    default_disclaimer = "📌 اخلاء مسؤولية\nهذا البوت هو للمساعده في استذكار العلاج ويجب عليك ان تسأل الصيدلاني."
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('disclaimer_text', ?)", (default_disclaimer,))
    
    default_welcome = "أهلاً بك! أرسل لي صورة الوصفة الطبية وسأقوم بقراءتها فوراً."
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('welcome_text', ?)", (default_welcome,))

    default_prompt = """أنت صيدلاني استشاري خبير جداً، دقيق ومحترف في قراءة الروشتات والخطوط الطبية اليدوية.
يرجى قراءة الصورة المرفقة واستخراج أسماء الأدوية وفقاً للتعليمات التالية بدقة متناهية:

1. تفحّص الصورة جيداً، وإن وُجدت أي إشارة إلى اختصاص الطبيب أو عمر المريض أو حالته، فاستفد منها كقرائن طبية لتدقيق قراءة الأدوية الملائمة.
2. إذا كان اسم الدواء المكتوب باليد مختصراً (مثل Duph أو Fol أو Cal أو Fer أو ما شابه)، قم فوراً بإكمال الاسم التجاري أو العلمي الكامل والمتداول له (ليصبح مثلاً: Duphaston, Folart, Caltrate, Ferose... إلخ) ولا تكتفِ بالمقطع الأول أبداً.
3. انتبه جيداً للرموز والاختصارات مثل حرف (ع) المتبوع برقم (مثل: ع 4، ع 20، ع 60): حرف (ع) يرمز حصراً إلى "العدد" أو "الكمية" الإجمالية وليست له علاقة بالجرعة أو الشكل الدوائي ولا يجب اعتباره جرعة.
4. يُذكر حصراً فقط وفقط: اسم العلاج كاملاً، الشكل الدوائي، والجرعة إن وجدت. امنع منعاً باتاً ذكر أي تفاصيل، شروحات، أو عدد مرات الاستخدام.
5. اكتب النص بشكل عادي وبدون استخدام أي نجوم (**) أو رموز تنسيق (Markdown).
6. اترك مسافة فارغة (سطر فارغ) بوضوح بين كل علاج والذي يليه.
7. العلاج الذي يستحيل قراءته تماماً اكتب مكانه حصراً: ------------
8. في نهاية الرسالة، اترك سطرين فارغين ثم اكتب حرفياً النص التالي بدون أي تعديل:

{disclaimer_saved}"""
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('prescription_prompt', ?)", (default_prompt,))
    
    conn.commit()
    conn.close()

init_db()

def get_setting(key):
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def update_setting(key, value):
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def get_current_admin_id():
    aid = get_setting('admin_id')
    return int(aid) if aid and aid.isdigit() else DEFAULT_ADMIN_ID

def get_all_keys():
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT id, key_value FROM api_keys')
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_next_key_from_db():
    global current_key_index
    keys = get_all_keys()
    if not keys:
        raise Exception("لا توجد أي مفاتيح API مخزنة في قاعدة البيانات! يرجى إضافتها عبر لوحة التحكم.")
    
    current_key_index = current_key_index % len(keys)
    key_id, key_value = keys[current_key_index]
    current_key_index += 1
    return key_value

def generate_content_with_retry(image_path, prompt):
    keys = get_all_keys()
    if not keys:
        raise Exception("لا توجد مفاتيح API مخزنة!")
        
    attempts = len(keys)
    model_name = get_setting('ai_model') or 'gemini-2.5-flash'

    last_error = None
    for _ in range(attempts):
        try:
            key = get_next_key_from_db()
            client = genai.Client(api_key=key)
            
            with open(image_path, "rb") as f:
                image_bytes = f.read()
                
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    genai.types.Part.from_bytes(
                        data=image_bytes,
                        mime_type="image/jpeg",
                    ),
                    prompt
                ]
            )
            return response.text
        except Exception as e:
            last_error = e
            time.sleep(0.5)
            continue
            
    raise Exception(f"فشلت كل المفاتيح. الخطأ الفعلي: {str(last_error)}")

def get_user(user_id, username=None, full_name=None):
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('SELECT free_tries, subscription_expiry, subscription_start, is_banned FROM users WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    
    if not row:
        limit = int(get_setting('free_tries_limit') or 3)
        cursor.execute('INSERT OR IGNORE INTO users (user_id, free_tries, username, full_name, is_banned) VALUES (?, ?, ?, ?, 0)', 
                       (user_id, limit, username, full_name))
        conn.commit()
        row = (limit, None, None, 0)
        
        try:
            u_name = f"@{username}" if username else "بدون معرف"
            f_name = full_name if full_name else "بدون اسم"
            notification = (
                "👤 **مستخدم جديد دخل للبوت!**\n\n"
                f"▫️ الاسم: {f_name}\n"
                f"▫️ المعرف: {u_name}\n"
                f"▫️ الـ ID: `{user_id}`"
            )
            bot.send_message(get_current_admin_id(), notification, parse_mode="Markdown")
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
    admin_id = get_current_admin_id()
    if user_id == admin_id:
        return True
    req_channel = get_setting('required_channel') or '@Saydlogy'
    try:
        member = bot.get_chat_member(req_channel, user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        else:
            return False
    except Exception:
        return False

def get_channel_keyboard():
    req_channel = get_setting('required_channel') or '@Saydlogy'
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📢 اشترك في القناة الآن", url=f"https://t.me/{req_channel.replace('@', '')}"))
    markup.add(InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_channel_sub"))
    return markup

def get_vip_status_keyboard():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📊 حالة اشتراكي", callback_data="check_my_vip_status"))
    return markup

def get_contact_admin_keyboard():
    admin_uname = get_setting('admin_username')
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("💬 تواصل مع المدير لتفعيل الاشتراك", url=f"https://t.me/{admin_uname}"))
    return markup

def get_admin_reply_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    btn1 = KeyboardButton("تفعيل الأشتراك")
    btn2 = KeyboardButton("تعديل إخلاء المسؤولية")
    markup.row(btn1, btn2)
    btn3 = KeyboardButton("احصائيات البوت")
    btn4 = KeyboardButton("الإذاعة")
    markup.row(btn3, btn4)
    btn5 = KeyboardButton("تعويض")
    btn6 = KeyboardButton("حظر / إلغاء حظر")
    markup.row(btn5, btn6)
    btn7 = KeyboardButton("⚙️ الإعدادات العامة")
    markup.row(btn7)
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = message.from_user
    admin_id = get_current_admin_id()
    user_data = get_user(user.id, user.username, user.first_name)
    
    if user_data[3] == 1 and user.id != admin_id:
        bot.reply_to(message, "⚠️ عذراً، تم حظرك من استخدام البوت.")
        return
    
    if user.id == admin_id:
        bot.reply_to(
            message, 
            "أهلاً بك يا مدير البوت 👑\nتم تفعيل لوحة التحكم السفلية الكاملة:", 
            reply_markup=get_admin_reply_keyboard()
        )
    else:
        if not check_subscription(user.id):
            req_channel = get_setting('required_channel') or '@Saydlogy'
            sub_warning = (
                "⚠️ **عذراً، يجب عليك الاشتراك في قناة البوت أولاً لتتمكن من استخدامه!**\n\n"
                f"يرجى الانضمام إلى القناة: {req_channel}\n"
                "بعد الانضمام، اضغط على زر (تحقق من الاشتراك) أدناه 👇"
            )
            bot.reply_to(message, sub_warning, parse_mode="Markdown", reply_markup=get_channel_keyboard())
            return
            
        welcome_msg = get_setting('welcome_text') or "أهلاً بك! أرسل لي صورة الوصفة الطبية وسأقوم بقراءتها فوراً."
        bot.reply_to(message, welcome_msg)

@bot.callback_query_handler(func=lambda call: call.data == "check_channel_sub")
def callback_check_channel(call):
    user_id = call.from_user.id
    
    if check_subscription(user_id):
        bot.answer_callback_query(call.id, "✅ تم التحقق من اشتراكك بنجاح!")
        try:
            bot.edit_message_text(
                "✅ شكراً لاشتراكك في القناة! يمكنك الآن استخدام البوت بكامل الميزات.\nأرسل لي صورة الوصفة الطبية الآن 📄",
                chat_id=call.message.chat.id,
                message_id=call.message.message_id
            )
        except Exception:
            bot.send_message(user_id, "✅ شكراً لاشتراكك! أرسل صورة الوصفة الآن.")
    else:
        bot.answer_callback_query(call.id, "⚠️ عذراً، أنت لست مشتركاً في القناة حتى الآن! يرجى الاشتراك ثم إعادة المحاولة.", show_alert=True)

@bot.message_handler(func=lambda message: message.from_user.id == get_current_admin_id() and message.text in [
    "تفعيل الأشتراك", "تعديل إخلاء المسؤولية", "احصائيات البوت", "الإذاعة", "تعويض", "حظر / إلغاء حظر", "⚙️ الإعدادات العامة"
])
def handle_admin_reply_buttons(message):
    text = message.text
    
    if text == "تفعيل الأشتراك":
        admin_states[get_current_admin_id()] = {"action": "waiting_activate_id"}
        bot.send_message(get_current_admin_id(), "✍️ أرسل الآن **آيدي المستخدم (ID)** المراد تفعيل اشتراكه:", parse_mode="Markdown")
        
    elif text == "تعديل إخلاء المسؤولية":
        current_disc = get_setting('disclaimer_text') or "غير محدد"
        admin_states[get_current_admin_id()] = {"action": "waiting_new_disclaimer"}
        bot.send_message(
            get_current_admin_id(), 
            f"📝 **إخلاء المسؤولية الحالي:**\n\n{current_disc}\n\n"
            "أرسل الآن **النص الجديد** لإخلاء المسؤولية ليتم اعتماده أسفل كل وصفة:", 
            parse_mode="Markdown"
        )
        
    elif text == "احصائيات البوت":
        show_stats()
        
    elif text == "الإذاعة":
        admin_states[get_current_admin_id()] = {"action": "waiting_broadcast_text"}
        bot.send_message(get_current_admin_id(), "📢 أرسل الآن **النص** الذي تريد إذاعته لجميع المستخدمين:", parse_mode="Markdown")
        
    elif text == "تعويض":
        admin_states[get_current_admin_id()] = {"action": "waiting_compensate_id"}
        bot.send_message(get_current_admin_id(), "🎁 أرسل أولاً **آيدي المستخدم (ID)** المراد تعويضه:", parse_mode="Markdown")
        
    elif text == "حظر / إلغاء حظر":
        admin_states[get_current_admin_id()] = {"action": "waiting_ban_id"}
        bot.send_message(get_current_admin_id(), "🚫 أرسل **آيدي المستخدم (ID)** لحظره أو إلغاء حظره:", parse_mode="Markdown")
        
    elif text == "⚙️ الإعدادات العامة":
        price = get_setting('sub_price')
        tries = get_setting('free_tries_limit')
        admin_uname = get_setting('admin_username')
        req_channel = get_setting('required_channel')
        ai_model = get_setting('ai_model')
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💵 تعديل سعر الاشتراك", callback_data="set_price"))
        markup.add(InlineKeyboardButton("🔢 تعديل عدد المحاولات المجانية", callback_data="set_tries"))
        markup.add(InlineKeyboardButton("📇 تعديل معرف التواصل", callback_data="set_admin_uname"))
        markup.add(InlineKeyboardButton("📢 تعديل قناة الإجبارية", callback_data="set_req_channel"))
        markup.add(InlineKeyboardButton("🤖 تعديل نموذج الذكاء الاصطناعي", callback_data="set_ai_model"))
        markup.add(InlineKeyboardButton("💬 تعديل رسالة الترحيب", callback_data="set_welcome_msg"))
        markup.add(InlineKeyboardButton("📝 تعديل برومفت قراءة الوصفة", callback_data="set_prescription_prompt"))
        markup.add(InlineKeyboardButton("🔑 إدارة مفاتيح الـ API", callback_data="manage_api_keys"))
        
        settings_msg = (
            "⚙️ **لوحة الإعدادات العامة الشاملة:**\n\n"
            f"💵 سعر الاشتراك: `{price}`\n"
            f"🔢 المحاولات المجانية: `{tries}`\n"
            f"📇 معرف التواصل: `@{admin_uname}`\n"
            f"📢 قناة الاشتراك: `{req_channel}`\n"
            f"🤖 نموذج الذكاء الاصطناعي: `{ai_model}`\n\n"
            "اختر الإعداد الذي تريد تعديله من الأزرار أدناه 👇"
        )
        bot.send_message(get_current_admin_id(), settings_msg, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["set_price", "set_tries", "set_admin_uname", "set_req_channel", "set_ai_model", "set_welcome_msg", "set_prescription_prompt"])
def callback_settings_buttons(call):
    admin_id = get_current_admin_id()
    if call.from_user.id != admin_id:
        return
    bot.answer_callback_query(call.id)
    
    if call.data == "set_price":
        admin_states[admin_id] = {"action": "waiting_new_price"}
        bot.send_message(admin_id, "💵 أرسل الآن **سعر الاشتراك الجديد** (مثال: `5,000 د.ع`):", parse_mode="Markdown")
    elif call.data == "set_tries":
        admin_states[admin_id] = {"action": "waiting_new_tries"}
        bot.send_message(admin_id, "🔢 أرسل الآن **عدد المحاولات المجانية الجديدة** برقم صحيح (مثال: `5`):", parse_mode="Markdown")
    elif call.data == "set_admin_uname":
        admin_states[admin_id] = {"action": "waiting_new_admin_uname"}
        bot.send_message(admin_id, "📇 أرسل الآن **معرف المدير الجديد** (بدون علامة @، مثال: `MPh_70`):", parse_mode="Markdown")
    elif call.data == "set_req_channel":
        admin_states[admin_id] = {"action": "waiting_new_req_channel"}
        bot.send_message(admin_id, "📢 أرسل الآن **معرف القناة الإجبارية الجديدة** (مع علامة @، مثال: `@MyChannel`):", parse_mode="Markdown")
    elif call.data == "set_ai_model":
        admin_states[admin_id] = {"action": "waiting_new_ai_model"}
        bot.send_message(admin_id, "🤖 أرسل الآن **اسم نموذج الذكاء الاصطناعي الجديد** (مثال: `gemini-2.5-flash`):", parse_mode="Markdown")
    elif call.data == "set_welcome_msg":
        admin_states[admin_id] = {"action": "waiting_new_welcome"}
        bot.send_message(admin_id, "💬 أرسل الآن **رسالة الترحيب الجديدة** التي تظهر للمستخدم عند إرسال `/start`:", parse_mode="Markdown")
    elif call.data == "set_prescription_prompt":
        current_p = get_setting('prescription_prompt') or ""
        admin_states[admin_id] = {"action": "waiting_new_prescription_prompt"}
        bot.send_message(admin_id, f"📝 **البرومفت الحالي لقراءة الوصفة:**\n\n`{current_p}`\n\nأرسل الآن **البرومفت الجديد** بالكامل:", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "manage_api_keys")
def callback_manage_api_keys(call):
    admin_id = get_current_admin_id()
    if call.from_user.id != admin_id:
        return
    bot.answer_callback_query(call.id)
    
    keys = get_all_keys()
    markup = InlineKeyboardMarkup()
    for kid, kval in keys:
        masked = f"...{kval[-6:]}" if len(kval) > 6 else kval
        markup.add(InlineKeyboardButton(f"❌ حذف مفتاح: {masked}", callback_data=f"del_key_{kid}"))
    
    markup.add(InlineKeyboardButton("➕ إضافة مفتاح جديد", callback_data="add_new_key"))
    markup.add(InlineKeyboardButton("🔍 فحص حالات المفاتيح", callback_data="check_api_keys"))
    
    bot.edit_message_text(
        f"🔑 **إدارة مفاتيح الـ API المخزنة:**\nإجمالي المفاتيح حالياً: `{len(keys)}`\n\nاختر الإجراء المطلوب أدناه 👇",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("del_key_"))
def callback_delete_key(call):
    admin_id = get_current_admin_id()
    if call.from_user.id != admin_id:
        return
    kid = call.data.replace("del_key_", "")
    
    conn = sqlite3.connect('users.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM api_keys WHERE id = ?', (kid,))
    conn.commit()
    conn.close()
    
    bot.answer_callback_query(call.id, "✅ تم حذف المفتاح بنجاح!")
    callback_manage_api_keys(call)

@bot.callback_query_handler(func=lambda call: call.data == "add_new_key")
def callback_add_new_key(call):
    admin_id = get_current_admin_id()
    if call.from_user.id != admin_id:
        return
    bot.answer_callback_query(call.id)
    admin_states[admin_id] = {"action": "waiting_api_key_text"}
    bot.send_message(admin_id, "➕ أرسل الآن **نص مفتاح الـ API الجديد** ليتم حفظه مباشرة:", parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "check_api_keys")
def callback_check_api_keys(call):
    admin_id = get_current_admin_id()
    if call.from_user.id != admin_id:
        return
    bot.answer_callback_query(call.id, "⏳ جاري فحص جميع المفاتيح...")
    
    keys = get_all_keys()
    model_name = get_setting('ai_model') or 'gemini-2.5-flash'
    report_lines = [
        "🔍 تقرير فحص مفاتيح الـ API:\n",
        f"📌 إجمالي المفاتيح: {len(keys)}\n"
    ]
    
    for i, (kid, key) in enumerate(keys):
        masked_key = f"...{key[-6:]}" if len(key) > 6 else "******"
        status = "❌ متوقف/خطأ"
        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model=model_name,
                contents="Test"
            )
            if response and response.text:
                status = "✅ صالح وفعال"
        except Exception as e:
            status = f"⚠️ خطأ: {str(e)[:30]}"
            
        report_lines.append(f"• مفتاح #{i+1} ({masked_key}): {status}")
        
    bot.send_message(admin_id, "\n".join(report_lines))

def show_stats():
    admin_id = get_current_admin_id()
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
                exp = datetime.strptime(row[0], '%Y-%m-%d %H:%M:%S')
                if exp > now:
                    active_vips += 1
            except Exception:
                pass
    conn.close()

    stats_msg = (
        "📈 **إحصائيات البوت:**\n\n"
        f"👥 إجمالي المستخدمين: {total_users}\n"
        f"⭐ المشتركين النشطين (VIP): {active_vips}\n"
        f"🆓 مستخدمي النسخة المجانية: {total_users - active_vips}"
    )
    bot.send_message(admin_id, stats_msg, parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())

@bot.message_handler(func=lambda message: message.from_user.id == get_current_admin_id() and get_current_admin_id() in admin_states)
def handle_admin_input(message):
    admin_id = get_current_admin_id()
    state = admin_states[admin_id].get("action")
    
    if state == "waiting_api_key_text":
        new_key_text = message.text.strip()
        try:
            conn = sqlite3.connect('users.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('INSERT INTO api_keys (key_value) VALUES (?)', (new_key_text,))
            conn.commit()
            conn.close()
            bot.reply_to(message, "✅ تم إضافة مفتاح الـ API الجديد وحفظه في قاعدة البيانات بنجاح!", reply_markup=get_admin_reply_keyboard())
        except sqlite3.IntegrityError:
            bot.reply_to(message, "⚠️ هذا المفتاح موجود مسبقاً في قاعدة البيانات!", reply_markup=get_admin_reply_keyboard())
        except Exception as e:
            bot.reply_to(message, f"⚠️ حدث خطأ: {e}", reply_markup=get_admin_reply_keyboard())
        finally:
            del admin_states[admin_id]

    elif state == "waiting_activate_id":
        try:
            target_id = int(message.text.strip())
            admin_states[admin_id] = {"action": "waiting_activate_days", "target_id": target_id}
            bot.reply_to(message, f"⏳ تم تحديد المستخدم `{target_id}`.\nالآن أرسل **عدد الأيام** المراد تفعيل الاشتراك بها (مثال: `7` أو `30` أو `365`):", parse_mode="Markdown")
        except ValueError:
            bot.reply_to(message, "⚠️ الآيدي يجب أن يكون أرقاماً فقط.")
            del admin_states[admin_id]

    elif state == "waiting_activate_days":
        try:
            days = int(message.text.strip())
            target_id = admin_states[admin_id].get("target_id")
            start_str, expiry_str = add_subscription_days(target_id, days)
            
            bot.reply_to(message, f"✅ تم تفعيل الاشتراك للمستخدم `{target_id}` بنجاح لمدة {days} يوماً!\nينتهي في: {expiry_str}", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
            
            vip_notification = (
                "🎉 **مبارك! تم تفعيل اشتراكك بنجاح.**\n\n"
                f"⏱️ **مدة الاشتراك المضافة:** `{days} يوم`\n"
                f"📅 **تاريخ البدء:** `{start_str}`\n"
                f"⏳ **تاريخ الانتهاء:** `{expiry_str}`\n\n"
                "يمكنك الآن استخدام البوت وقراءة الوصفات الطبية بلا حدود وبكامل الميزات!\n"
                "اضغط على الزر أدناه لمتابعة حالة اشتراكك في أي وقت 👇"
            )
            try:
                bot.send_message(target_id, vip_notification, parse_mode="Markdown", reply_markup=get_vip_status_keyboard())
            except Exception:
                pass
                
        except ValueError:
            bot.reply_to(message, "⚠️ عدد الأيام يجب أن يكون رقماً صحيحاً.")
        finally:
            del admin_states[admin_id]
            
    elif state == "waiting_new_disclaimer":
        new_disc = message.text.strip()
        update_setting('disclaimer_text', new_disc)
        bot.reply_to(message, f"✅ **تم تحديث رسالة إخلاء المسؤولية بنجاح لتصبح:**\n\n{new_disc}", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
        del admin_states[admin_id]

    elif state == "waiting_new_welcome":
        new_wel = message.text.strip()
        update_setting('welcome_text', new_wel)
        bot.reply_to(message, f"✅ **تم تحديث رسالة الترحيب بنجاح لتصبح:**\n\n{new_wel}", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
        del admin_states[admin_id]

    elif state == "waiting_new_prescription_prompt":
        new_p = message.text.strip()
        update_setting('prescription_prompt', new_p)
        bot.reply_to(message, "✅ تم حفظ البرومفت الجديد بنجاح!", reply_markup=get_admin_reply_keyboard())
        del admin_states[admin_id]
            
    elif state == "waiting_broadcast_text":
        text_to_send = message.text.strip()
        conn = sqlite3.connect('users.db', check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users')
        users = cursor.fetchall()
        conn.close()
        
        sent_count = 0
        failed_count = 0
        msg = bot.reply_to(message, "⏳ جاري إرسال الرسالة لجميع المستخدمين...")
        
        for u in users:
            uid = u[0]
            if uid == admin_id:
                continue
            try:
                bot.send_message(uid, text_to_send, parse_mode="Markdown")
                sent_count += 1
            except Exception:
                failed_count += 1
                
        bot.edit_message_text(
            f"✅ تمت عملية الإذاعة بنجاح!\n\n"
            f"📨 تم الإرسال إلى: {sent_count} مستخدم\n"
            f"❌ فشل الإرسال لـ: {failed_count} مستخدم",
            chat_id=message.chat.id,
            message_id=msg.message_id
        )
        bot.send_message(admin_id, "🛠️ لوحة التحكم الرئيسية:", reply_markup=get_admin_reply_keyboard())
        del admin_states[admin_id]
        
    elif state == "waiting_compensate_id":
        try:
            target_id = int(message.text.strip())
            admin_states[admin_id] = {"action": "waiting_compensate_days", "target_id": target_id}
            bot.reply_to(message, f"⏳ تم تحديد المستخدم `{target_id}`.\nالآن أرسل **عدد الأيام** المراد تعويضه بها (مثلاً: `5`):", parse_mode="Markdown")
        except ValueError:
            bot.reply_to(message, "⚠️ الآيدي يجب أن يكون أرقاماً صحيحة.")
            del admin_states[admin_id]
            
    elif state == "waiting_compensate_days":
        try:
            days = int(message.text.strip())
            target_id = admin_states[admin_id].get("target_id")
            start_str, expiry_str = add_subscription_days(target_id, days)
            bot.reply_to(message, f"🎁 تم تعويض المستخدم `{target_id}` بـ {days} أيام بنجاح!\nتاريخ الانتهاء الجديد: {expiry_str}", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
            
            compensate_notification = (
                f"🎁 **تمت إضافة رصيد تعويض إلى اشتراكك بقيمة `{days} أيام إضافية`!**\n\n"
                f"⏳ **تاريخ الانتهاء الجديد:** `{expiry_str}`"
            )
            try:
                bot.send_message(target_id, compensate_notification, parse_mode="Markdown", reply_markup=get_vip_status_keyboard())
            except Exception:
                pass
        except ValueError:
            bot.reply_to(message, "⚠️ عدد الأيام يجب أن يكون رقماً صحيحاً.")
        finally:
            del admin_states[admin_id]

    elif state == "waiting_ban_id":
        try:
            target_id = int(message.text.strip())
            conn = sqlite3.connect('users.db', check_same_thread=False)
            cursor = conn.cursor()
            cursor.execute('SELECT is_banned FROM users WHERE user_id = ?', (target_id,))
            row = cursor.fetchone()
            
            if not row:
                bot.reply_to(message, "⚠️ هذا المستخدم غير مسجل في قاعدة البيانات بعد.", reply_markup=get_admin_reply_keyboard())
            else:
                current_ban = row[0]
                new_ban = 0 if current_ban == 1 else 1
                cursor.execute('UPDATE users SET is_banned = ? WHERE user_id = ?', (new_ban, target_id))
                conn.commit()
                
                status_text = "حظر المستخدم بنجاح 🚫" if new_ban == 1 else "إلغاء حظر المستخدم بنجاح ✅"
                bot.reply_to(message, f"✅ {status_text} (ID: `{target_id}`)", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
                
                try:
                    if new_ban == 1:
                        bot.send_message(target_id, "⚠️ عذراً، تم حظرك من استخدام البوت من قبل الإدارة.")
                    else:
                        bot.send_message(target_id, "✅ تم رفع الحظر عنك، يمكنك استخدام البوت الآن.")
                except Exception:
                    pass
            conn.close()
        except ValueError:
            bot.reply_to(message, "⚠️ الآيدي يجب أن يكون أرقاماً صحيحة.")
        finally:
            del admin_states[admin_id]

    elif state == "waiting_new_price":
        new_price = message.text.strip()
        update_setting('sub_price', new_price)
        bot.reply_to(message, f"✅ تم تحديث سعر الاشتراك بنجاح إلى: `{new_price}`", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
        del admin_states[admin_id]

    elif state == "waiting_new_tries":
        try:
            new_tries = int(message.text.strip())
            update_setting('free_tries_limit', str(new_tries))
            bot.reply_to(message, f"✅ تم تحديث عدد المحاولات المجانية للمستخدمين الجدد إلى: `{new_tries}`", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
        except ValueError:
            bot.reply_to(message, "⚠️ يجب إدخال رقم صحيح.")
        finally:
            del admin_states[admin_id]

    elif state == "waiting_new_admin_uname":
        new_uname = message.text.strip().replace("@", "")
        update_setting('admin_username', new_uname)
        bot.reply_to(message, f"✅ تم تحديث معرف المدير بنجاح إلى: `@{new_uname}`", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
        del admin_states[admin_id]

    elif state == "waiting_new_req_channel":
        new_channel = message.text.strip()
        update_setting('required_channel', new_channel)
        bot.reply_to(message, f"✅ تم تحديث قناة الاشتراك الإجباري بنجاح إلى: `{new_channel}`", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
        del admin_states[admin_id]

    elif state == "waiting_new_ai_model":
        new_model = message.text.strip()
        update_setting('ai_model', new_model)
        bot.reply_to(message, f"✅ تم تحديث نموذج الذكاء الاصطناعي بنجاح إلى: `{new_model}`", parse_mode="Markdown", reply_markup=get_admin_reply_keyboard())
        del admin_states[admin_id]

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
        bot.send_message(user_id, "⚠️ ليس لديك اشتراك نشط حالياً أو أن اشتراكك قد انتهى.")
        return
        
    start_str, expiry_str = row[0], row[1]
    try:
        expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
    except Exception:
        bot.send_message(user_id, "⚠️ حدث خطأ في قراءة تاريخ الاشتراك.")
        return
        
    now = datetime.now()
    
    if expiry_date <= now:
        bot.send_message(user_id, "⚠️ عذراً، لقد انتهت صلاحية اشتراكك.")
        return
        
    remaining_time = expiry_date - now
    remaining_days = remaining_time.days
    admin_uname = get_setting('admin_username')
    
    status_message = (
        "⭐ **تفاصيل اشتراكك الفعال:**\n\n"
        f"📅 تاريخ البدء: `{start_str}`\n"
        f"⏳ تاريخ الانتهاء: `{expiry_str}`\n"
        f"⏱️ الأيام الباقية لنهاية الاشتراك: `~{remaining_days} يوم`\n\n"
        f"شكراً لثقتك بنا! للإستفسار أو التجديد تواصل مع المدير: [{admin_uname}](https://t.me/{admin_uname})"
    )
    bot.send_message(user_id, status_message, parse_mode="Markdown", reply_markup=get_vip_status_keyboard())

@bot.message_handler(content_types=['photo'])
def handle_prescription(message):
    user_id = message.from_user.id
    admin_id = get_current_admin_id()
    req_channel = get_setting('required_channel') or '@Saydlogy'
    
    user_data = get_user(user_id, message.from_user.username, message.from_user.first_name)
    if user_data[3] == 1 and user_id != admin_id:
        bot.reply_to(message, "⚠️ عذراً، تم حظرك من استخدام البوت.")
        return
    
    if user_id != admin_id:
        if not check_subscription(user_id):
            sub_warning = (
                "⚠️ **عذراً، يجب عليك الاشتراك في قناة البوت أولاً لتتمكن من استخدامه!**\n\n"
                f"يرجى الانضمام إلى القناة: {req_channel}\n"
                "بعد الانضمام، اضغط على زر (تحقق من الاشتراك) أدناه 👇"
            )
            bot.reply_to(message, sub_warning, parse_mode="Markdown", reply_markup=get_channel_keyboard())
            return

        free_tries, expiry_str, _ = user_data[0], user_data[1], user_data[2]
        
        is_vip = False
        if expiry_str:
            try:
                expiry_date = datetime.strptime(expiry_str, '%Y-%m-%d %H:%M:%S')
                if expiry_date > datetime.now():
                    is_vip = True
            except Exception:
                pass

        if not is_vip and free_tries <= 0:
            current_price = get_setting('sub_price')
            tries_limit = get_setting('free_tries_limit')
            subscription_text = (
                f"⚠️ انتهت محاولاتك المجانية ({tries_limit} محاولات)!\n\n"
                f"للاستمرار في استخدام البوت وقراءة الوصفات بدون حدود، يرجى الإشتراك بقيمة {current_price}.\n\n"
                "💳 طريقة الدفع:\n"
                "- زين كاش\n"
                "- ماستركارد\n\n"
                f"ال ID الخاص بك : `{user_id}`\n\n"
                "للتفعيل تواصل معنا عبر الزر أدناه 👇"
            )
            bot.reply_to(message, subscription_text, parse_mode="Markdown", reply_markup=get_contact_admin_keyboard())
            return
    else:
        is_vip = True

    msg = bot.reply_to(message, "⏳ جاري قراءة الوصفة الطبية بدقة، ثوانٍ...")
    
    image_path = f"prescription_{user_id}_{message.message_id}.jpg"
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open(image_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        disclaimer_saved = get_setting('disclaimer_text') or "📌 اخلاء مسؤولية\nهذا البوت هو للمساعده في استذكار العلاج ويجب عليك ان تسأل الصيدلاني."
        prompt_template = get_setting('prescription_prompt') or ""
        
        prompt = prompt_template.format(disclaimer_saved=disclaimer_saved)
        
        result_text = generate_content_with_retry(image_path, prompt)
        
        bot.edit_message_text(result_text, chat_id=message.chat.id, message_id=msg.message_id)
        
        if user_id != admin_id and not is_vip:
            row = get_user(user_id)
            if row:
                free_tries = row[0]
                new_tries = max(0, free_tries - 1)
                update_free_tries(user_id, new_tries)
            
    except Exception as e:
        bot.edit_message_text("عذراً، حدث ضغط مؤقت في الخدمة، يرجى إرسال الصورة من جديد 📷", chat_id=message.chat.id, message_id=msg.message_id)
        
    finally:
        if os.path.exists(image_path):
            os.remove(image_path)

print("البوت يعمل بكفاءة وقابل للتعديل بالكامل من التليجرام...")

while True:
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60, skip_pending=True)
    except Exception as e:
        print(f"حدث خطأ في الاتصال: {e}")
        time.sleep(10)
