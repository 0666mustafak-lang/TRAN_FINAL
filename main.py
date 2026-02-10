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

bot = Client("bot_session", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)
user_data = {}

def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

# --- HELPERS: GET PROTECTED SESSIONS ---
async def get_protected_accs():
    accs = []
    for k, v in os.environ.items():
        if k.startswith("TG_SESSION_"):
            # نحاول استخراج الاسم بشكل سريع
            accs.append((k, k.replace("TG_SESSION_", "")))
    return accs

# --- START & AUTH ---
@bot.on_message(filters.command("start") & filters.private)
async def start(client, message):
    uid = message.from_user.id
    user_data[uid] = {"step": "idle"}
    await message.reply("📟 **مرحباً بك في النظام الشامل**\n\nاختر وسيلة الدخول:", 
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛡 الحسابات المحمية", callback_data="sessions")],
            [InlineKeyboardButton("📲 دخول مؤقت", callback_data="temp_login")],
            [InlineKeyboardButton("🧹 تسجيل خروج المؤقت", callback_data="clear_temp")]
        ]))

# --- CALLBACK HANDLER ---
@bot.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    uid = query.from_user.id
    data = query.data
    s = user_data.setdefault(uid, {})

    if data == "sessions":
        accs = await get_protected_accs()
        if not accs: return await query.answer("❌ لا توجد حسابات محمية في Variables ريلواي", show_alert=True)
        btns = [[InlineKeyboardButton(name, callback_data=f"load_{key}")] for key, name in accs]
        await query.edit_message_text("🛡 اختر الحساب المحمي:", reply_markup=InlineKeyboardMarkup(btns))

    elif data.startswith("load_"):
        sess_key = data.replace("load_", "")
        s["user_client"] = Client(f"u_{uid}", api_id=int(API_ID), api_hash=API_HASH, session_string=os.getenv(sess_key))
        await s["user_client"].connect()
        await show_main_menu(query)

    elif data == "temp_login":
        s["step"] = "phone"
        await query.edit_message_text("📲 أرسل رقم الهاتف (مثال: +964...):")
    
    elif data == "clear_temp":
        if "user_client" in s:
            try: await s["user_client"].log_out()
            except: pass
        s.clear()
        await query.edit_message_text("🧹 تم تسجيل الخروج بنجاح.")

    elif data == "main_menu": await show_main_menu(query)
    elif data == "transfer_menu":
        await query.edit_message_text("📤 **قائمة النقل:**", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 نقل عادي (وصف)", callback_data="mode_normal")],
            [InlineKeyboardButton("📦 نقل تجميعي (10/10)", callback_data="mode_batch")],
            [InlineKeyboardButton("🔙 عودة", callback_data="main_menu")]
        ]))

    elif data.startswith("mode_"):
        s["mode"] = data.split("_")[1]
        s["step"] = "get_delay"
        await query.edit_message_text("⏱️ أرسل التأخير (بالثواني):")

    elif data == "steal_fast":
        s.update({"mode": "steal", "delay": 0, "step": "get_source"})
        await query.edit_message_text("⚡ **السرقة السريعة (10/10)**\n🔗 أرسل رابط القناة المصدر:")

    elif data == "clean_admin":
        await show_admin_chats(client, query.message, s.get("user_client"))

    elif data.startswith("do_clean_"):
        chat_id = int(data.split("_")[2])
        asyncio.create_task(run_cleaning(client, query, chat_id))

# --- LOGIC HANDLER (TEXT INPUT) ---
@bot.on_message(filters.private & filters.text & ~filters.command("start"))
async def logic_handler(client, message: Message):
    uid = message.from_user.id
    if uid not in user_data: return
    s = user_data[uid]
    step = s.get("step")

    if step == "phone":
        temp = Client(f"u_{uid}", api_id=int(API_ID), api_hash=API_HASH)
        await temp.connect()
        try:
            sent_code = await temp.send_code(message.text.replace(" ", ""))
            s.update({"user_client": temp, "phone": message.text, "hash": sent_code.phone_code_hash, "step": "code"})
            await message.reply("🔐 أرسل الكود:")
        except Exception as e: await message.reply(f"❌ خطأ: {e}")

    elif step == "code":
        try:
            await s["user_client"].sign_in(s["phone"], s["hash"], message.text)
            await show_main_menu(message)
        except SessionPasswordNeeded:
            s["step"] = "2fa"
            await message.reply("🔐 أرسل كلمة سر التحقق بخطوتين:")
        except Exception as e: await message.reply(f"❌ خطأ: {e}")

    elif step == "2fa":
        await s["user_client"].check_password(message.text)
        await show_main_menu(message)

    elif step == "get_delay":
        s["delay"] = int(message.text) if message.text.isdigit() else 10
        s["step"] = "get_target"
        await message.reply("🔗 أرسل معرف القناة الهدف (مثال @channel):")

    elif step == "get_target":
        s["target"] = message.text; s["running"] = True
        s["status"] = await message.reply("🚀 جاري البدء...")
        asyncio.create_task(run_transfer_engine(uid))

    elif step == "get_source":
        s["source"] = message.text; s["target"] = "me"; s["running"] = True
        s["status"] = await message.reply("⚡ جاري السرقة...")
        asyncio.create_task(run_transfer_engine(uid))

# --- FUNCTIONS & ENGINES ---
async def show_main_menu(obj):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 النقل", callback_data="transfer_menu")],
        [InlineKeyboardButton("⚡ السرقة السريعة", callback_data="steal_fast")],
        [InlineKeyboardButton("🧹 تنظيف الإدمن", callback_data="clean_admin")]
    ])
    if isinstance(obj, Message): await obj.reply("✅ القائمة الرئيسية:", reply_markup=kb)
    else: await obj.edit_message_text("✅ القائمة الرئيسية:", reply_markup=kb)

async def show_admin_chats(bot_client, message, user_client):
    buttons = []
    m = await message.reply("🔍 جاري فحص صلاحياتك...")
    async for dialog in user_client.get_dialogs():
        chat = dialog.chat
        if chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]:
            if chat.permissions or chat.is_creator: # حل مشكلة 271
                buttons.append([InlineKeyboardButton(f"🧹 {chat.title[:20]}", callback_data=f"do_clean_{chat.id}")])
    if buttons: await m.edit("✅ اختر لتنظيفه:", reply_markup=InlineKeyboardMarkup(buttons))
    else: await m.edit("❌ لم أجد قنوات أنت إدمن فيها.")

async def run_transfer_engine(uid):
    s = user_data[uid]
    uc = s["user_client"]
    mode, delay = s["mode"], s["delay"]
    src, dst = (s["source"], "me") if mode == "steal" else ("me", s["target"])
    
    sent_count = 0
    batch = []
    async for msg in uc.get_chat_history(src):
        if not s.get("running"): break
        if not msg.video: continue

        if mode in ["batch", "steal"]:
            batch.append(msg.id)
            if len(batch) == 10:
                await uc.copy_messages(dst, src, batch)
                sent_count += 10
                await s["status"].edit(f"📊 التقدم: {sent_count}")
                batch = []
                # قفل التأخير: يطبق فقط إذا كان هناك قيمة (يعني في النقل وليس السرقة)
                if delay > 0: await asyncio.sleep(delay)
        else:
            await uc.copy_messages(dst, src, msg.id, caption=clean_caption(msg.caption))
            sent_count += 1
            await s["status"].edit(f"📊 التقدم: {sent_count}")
            await asyncio.sleep(delay)

    if batch: await uc.copy_messages(dst, src, batch)
    await s["status"].edit(f"✅ اكتملت العملية: {sent_count} مقطع")

async def run_cleaning(client, callback_query, chat_id):
    uid = callback_query.from_user.id
    uc = user_data[uid]["user_client"]
    status = await callback_query.edit_message_text("🔄 جاري التنظيف (رسائل + أعضاء)...")
    s_count, b_count = 0, 0
    # تنظيف الخدمة
    async for msg in uc.get_chat_history(chat_id, limit=300):
        if msg.service:
            try: await msg.delete(); s_count += 1
            except: pass
    # طرد الأعضاء
    async for member in uc.get_chat_members(chat_id):
        if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            try:
                await uc.ban_chat_member(chat_id, member.user.id)
                b_count += 1
                if b_count % 10 == 0: await status.edit(f"📊 التقدم: 🧹 {s_count} | 👤 {b_count}")
            except FloodWait as e: await asyncio.sleep(e.value)
            except: continue
    await status.edit(f"✅ تم التنظيف: 🧹 {s_count} رسالة | 👤 {b_count} عضو")

print("✅ Bot is Online!")
bot.run()
