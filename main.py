import os
import asyncio
import re
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import SessionPasswordNeeded, FloodWait

# --- CONFIG ---
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"

# تحميل المستخدمين المسموح لهم
def load_authorized():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE, "r") as f:
            return set(int(line.strip()) for line in f if line.strip().isdigit())
    return set()

AUTHORIZED_USERS = load_authorized()

def save_authorized(uid):
    AUTHORIZED_USERS.add(uid)
    with open(AUTH_FILE, "a") as f:
        f.write(f"{uid}\n")

bot = Client("bot_session", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)
user_data = {}

def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_protected_accs():
    accs = []
    for k, v in os.environ.items():
        if k.startswith("TG_SESSION_"):
            accs.append((k, k.replace("TG_SESSION_", "")))
    return accs

# --- START ---
@bot.on_message(filters.command("start") & filters.private)
async def start(client, message):
    uid = message.from_user.id
    if uid not in AUTHORIZED_USERS:
        await message.reply("🔐 **أرسل رمز الدخول للمتابعة:**")
        return
    
    user_data[uid] = {"step": "idle"}
    # القائمة الأصلية اللي طلبتها بالظبط
    await message.reply("اختر طريقة الدخول:", 
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛡 الحسابات المحمية", callback_data="sessions")],
            [InlineKeyboardButton("📲 دخول مؤقت", callback_data="temp_login")],
            [InlineKeyboardButton("🔑 استخراج سيشن", callback_data="extract_session")],
            [InlineKeyboardButton("🧹 تسجيل خروج المؤقت", callback_data="clear_temp")]
        ]))

# --- CALLBACK HANDLER ---
@bot.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    if uid not in AUTHORIZED_USERS:
        return await query.answer("🔐 سجل دخول بالرمز أولاً", show_alert=True)
    
    data = query.data
    s = user_data.setdefault(uid, {})

    if data == "sessions":
        accs = await get_protected_accs()
        if not accs: return await query.answer("❌ لا توجد حسابات محمية", show_alert=True)
        btns = [[InlineKeyboardButton(name, callback_data=f"load_{key}")] for key, name in accs]
        await query.edit_message_text("🛡 اختر الحساب المحمي:", reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("load_"):
        sess_key = data.replace("load_", "")
        s["user_client"] = Client(f"u_{uid}", api_id=int(API_ID), api_hash=API_HASH, session_string=os.getenv(sess_key))
        await s["user_client"].connect()
        await show_main_menu(query)

    elif data == "temp_login":
        s["step"] = "phone"
        await query.edit_message_text("📲 أرسل رقم الهاتف:")

    elif data == "extract_session":
        await query.edit_message_text("🔑 ميزة استخراج السيشن قيد العمل...") # يمكنك ربطها بنفس منطق الدخول
    
    elif data == "clear_temp":
        if "user_client" in s:
            try: await s["user_client"].log_out()
            except: pass
        s.clear()
        await query.edit_message_text("🧹 تم تسجيل الخروج ومسح الجلسة.")

    elif data == "main_menu": await show_main_menu(query)
    
    elif data == "transfer_menu":
        await query.edit_message_text("قائمة النقل:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 نقل عادي (وصف)", callback_data="mode_normal")],
            [InlineKeyboardButton("📦 نقل تجميعي (بدون وصف)", callback_data="mode_batch")],
            [InlineKeyboardButton("🗑️ إعادة ضبط", callback_data="main_menu")]
        ]))

    elif data.startswith("mode_"):
        s["mode"] = data.split("_")[1]
        s["step"] = "get_delay"
        await query.edit_message_text("⏱️ أرسل التأخير المطلوب:")

    elif data == "steal":
        s.update({"mode": "steal", "delay": 0, "step": "get_source"})
        await query.edit_message_text("⚡ أرسل رابط القناة:")
    
    elif data == "steal_protected":
        s.update({"mode": "steal_protected", "delay": 0, "step": "get_source"})
        await query.edit_message_text("🔓 أرسل رابط القناة المحمية:")

    elif data == "clean_menu":
        await show_admin_chats(client, query.message, s.get("user_client"))

    elif data.startswith("do_clean_"):
        chat_id = int(data.split("_")[2])
        asyncio.create_task(run_cleaning(client, query, chat_id))

# --- LOGIC HANDLER ---
@bot.on_message(filters.private & filters.text & ~filters.command("start"))
async def logic_handler(client, message: Message):
    uid = message.from_user.id
    text = message.text.strip()

    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            save_authorized(uid); await message.reply("✅ تم الدخول، أرسل /start")
        else: await message.reply("🔐 أرسل رمز الدخول")
        return

    if uid not in user_data: return
    s = user_data[uid]
    step = s.get("step")

    if step == "phone":
        temp = Client(f"u_{uid}", api_id=int(API_ID), api_hash=API_HASH)
        await temp.connect()
        try:
            sent_code = await temp.send_code(text.replace(" ", ""))
            s.update({"user_client": temp, "phone": text, "hash": sent_code.phone_code_hash, "step": "code"})
            await message.reply("🔑 أرسل كود التحقق")
        except Exception as e: await message.reply(f"❌ خطأ: {e}")

    elif step == "code":
        try:
            await s["user_client"].sign_in(s["phone"], s["hash"], text)
            await show_main_menu(message)
        except SessionPasswordNeeded:
            s["step"] = "2fa"; await message.reply("🔐 أرسل رمز 2FA")
        except Exception as e: await message.reply(f"❌ خطأ: {e}")

    elif step == "2fa":
        await s["user_client"].check_password(text)
        await show_main_menu(message)

    elif step == "get_delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "get_target"; await message.reply("🔗 أرسل الهدف")

    elif step == "get_target":
        s["target"] = text; s["running"] = True
        s["status"] = await message.reply("🚀 بدء العملية...")
        asyncio.create_task(run_transfer_engine(uid))

    elif step == "get_source":
        s["source"] = text; s["target"] = "me"; s["running"] = True
        s["status"] = await message.reply("⚡ بدء السرقة...")
        asyncio.create_task(run_transfer_engine(uid))

# --- ENGINES ---
async def show_main_menu(obj):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 النقل", callback_data="transfer_menu")],
        [InlineKeyboardButton("⚡ السرقة", callback_data="steal")],
        [InlineKeyboardButton("🔓 السرقة المحمية", callback_data="steal_protected")],
        [InlineKeyboardButton("🧹 تنظيف الإدمن", callback_data="clean_menu")]
    ])
    msg = "اختر العملية:"
    if isinstance(obj, Message): await obj.reply(msg, reply_markup=kb)
    else: await obj.edit_message_text(msg, reply_markup=kb)

async def show_admin_chats(bot_client, message, user_client):
    buttons = []
    m = await message.reply("🔍 جاري الفحص...")
    async for dialog in user_client.get_dialogs():
        if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]:
            if dialog.chat.permissions or dialog.chat.is_creator: # حل 271
                buttons.append([InlineKeyboardButton(f"🧹 {dialog.chat.title[:20]}", callback_data=f"do_clean_{dialog.chat.id}")])
    if buttons: await m.edit("✅ اختر لتنظيفه:", reply_markup=InlineKeyboardMarkup(buttons))
    else: await m.edit("❌ لا توجد قنوات إدمن")

async def run_transfer_engine(uid):
    s = user_data[uid]; uc = s["user_client"]
    mode, delay = s["mode"], s["delay"]
    src, dst = (s["source"], "me") if mode.startswith("steal") else ("me", s["target"])
    sent_count, batch = 0, []
    async for msg in uc.get_chat_history(src):
        if not s.get("running"): break
        if not msg.video: continue
        if mode in ["batch", "steal", "steal_protected"]:
            batch.append(msg.id)
            if len(batch) == 10:
                await uc.copy_messages(dst, src, batch) # يرسل وينتظر الإرسال الفعلي
                sent_count += 10
                await s["status"].edit(f"📊 التقدم: {sent_count}")
                batch = []
                if delay > 0: await asyncio.sleep(delay) # حل مشكلة الدفعتين المتتاليتين
        else:
            await uc.copy_messages(dst, src, msg.id, caption=clean_caption(msg.caption))
            sent_count += 1
            await s["status"].edit(f"📊 التقدم: {sent_count}")
            await asyncio.sleep(delay)
    if batch: await uc.copy_messages(dst, src, batch)
    await s["status"].edit(f"✅ اكتملت العملية: {sent_count}")

async def run_cleaning(client, callback_query, chat_id):
    uid = callback_query.from_user.id
    uc = user_data[uid]["user_client"]
    status = await callback_query.edit_message_text("🔄 **جاري التنظيف...**")
    try:
        s_count = 0; service_msg_ids = []
        async for message in uc.get_chat_history(chat_id, limit=500):
            if message.service:
                service_msg_ids.append(message.id); s_count += 1
        if service_msg_ids:
            for i in range(0, len(service_msg_ids), 100):
                await uc.delete_messages(chat_id, service_msg_ids[i:i+100])
                await asyncio.sleep(0.5)
        
        b_count = 0
        async for member in uc.get_chat_members(chat_id):
            if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                try:
                    await uc.ban_chat_member(chat_id, member.user.id); b_count += 1
                    if b_count % 5 == 0: await status.edit(f"📊 **التقدم:**\n👤 مطرودين: `{b_count}`\n🗑 رسائل: `{s_count}`")
                    await asyncio.sleep(2) # تأخير آمن كما في كودك
                except: continue
        await status.edit(f"✅ اكتمل التنظيف!\n👤 المطرودين: `{b_count}`\n🗑 الرسائل: `{s_count}`")
    except Exception as e: await status.edit(f"❌ خطأ: {e}")

bot.run()
