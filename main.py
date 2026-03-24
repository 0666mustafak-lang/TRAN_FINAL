import os
import asyncio
import re
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError as Telethon2FA, FloodWaitError
from pyrogram import Client as PyroClient, enums

# ================= CONFIG =================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"

def load_authorized():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE) as f:
            try: return set(map(int, f.read().splitlines()))
            except: return set()
    return set()

AUTHORIZED_USERS = load_authorized()
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}

def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_accounts():
    accs = []
    session_keys = sorted([k for k in os.environ.keys() if k.startswith("TG_SESSION_")])
    for k in session_keys:
        try:
            temp_client = TelegramClient(StringSession(os.environ[k]), API_ID, API_HASH)
            await temp_client.connect()
            if await temp_client.is_user_authorized():
                me = await temp_client.get_me()
                name = me.first_name if me.first_name else k.replace("TG_SESSION_", "")
                accs.append((k, name))
            await temp_client.disconnect()
        except: continue
    return accs

# ================= ENGINE (The Fixed Part) =================
async def run_engine(uid):
    s = state[uid]
    client = s["client"]
    mode = s["mode"]
    src = s.get("source", "me")
    dst = s.get("target", "me")
    s["running"] = True
    
    try:
        m_info = await client.get_messages(src, limit=0)
        total = m_info.total
    except: total = "???"

    # السحب من الأحدث للأقدم مع limit=None يضمن جلب كل شيء بدون توقف عند 99
    async for m in client.iter_messages(src, limit=None):
        if not s.get("running"): break
        if not m.video: continue

        try:
            # النقل الذكي: استخدام m.media أسرع وأخف
            await client.send_file(dst, m.media, caption=clean_caption(m.text))
            
            s["sent"] += 1
            if s["sent"] % 2 == 0: # تحديث العداد كل مقطعين لسرعة الواجهة
                await s["status"].edit(f"📊 التقدم: {s['sent']} / {total}\n🚀 الوضع: {mode}")

            # التحكم في التأخير حسب الوضع
            if mode in ["steal", "steal_protected"]:
                await asyncio.sleep(1) # سرعة عالية للسرقة
            else:
                await asyncio.sleep(s.get("delay", 10)) # التزام بتأخيرك للنقل العادي

        except FloodWaitError as f:
            await s["status"].edit(f"⏳ حماية تليجرام! سأنتظر {f.seconds} ثانية...")
            await asyncio.sleep(f.seconds + 5)
        except Exception as e:
            print(f"Error: {e}")
            continue
            
    await s["status"].edit(f"✅ تم اكتمال المهمة بنجاح!\n📦 الإجمالي: {s['sent']}")

# ================= ROUTER & CALLBACKS (Keeping your Menus) =================
@bot.on(events.NewMessage)
async def router(event):
    uid = event.sender_id
    text = (event.text or "").strip()
    s = state.setdefault(uid, {})

    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            AUTHORIZED_USERS.add(uid)
            with open(AUTH_FILE, "a") as f: f.write(f"{uid}\n")
            await event.respond("✅ تم التفعيل، أرسل /start")
        else: await event.respond("🔐 أرسل رمز الدخول:")
        return

    if text == "/start":
        await event.respond("📟 **نظام التحكم المتكامل**", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج سيشن (جديد)", b"extract_session")],
            [Button.inline("🧹 خروج المؤقت", b"clear_temp")]
        ])
        return

    step = s.get("step")
    # --- استخراج السيشن والدخول المؤقت (نفس منطقك الأصلي تماماً) ---
    if step == "ex_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        s["ex_c"] = c; await c.connect()
        try:
            sent = await c.send_code_request(text)
            s.update({"ex_p": text, "ex_h": sent.phone_code_hash, "step": "ex_code"})
            await event.respond("🔑 كود الاستخراج:")
        except Exception as e: await event.respond(f"❌: {e}")
    elif step == "ex_code":
        try:
            await s["ex_c"].sign_in(s["ex_p"], text, phone_code_hash=s["ex_h"])
            await event.respond(f"✅ السيشن:\n`{s['ex_c'].session.save()}`"); await s["ex_c"].disconnect()
        except Telethon2FA:
            s["step"] = "ex_2fa"; await event.respond("🔐 رمز 2FA:")
    elif step == "ex_2fa":
        await s["ex_c"].sign_in(password=text)
        await event.respond(f"✅ السيشن:\n`{s['ex_c'].session.save()}`"); await s["ex_c"].disconnect()

    elif step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        s["client"] = c; await c.connect()
        try:
            sent = await c.send_code_request(text)
            s.update({"phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
            await event.respond("🔐 كود التحقق:")
        except Exception as e: await event.respond(f"❌: {e}")
    elif step == "temp_code":
        try:
            await s["client"].sign_in(s["phone"], text, phone_code_hash=s["hash"])
            s["raw_session"] = s["client"].session.save(); await show_main_menu(event)
        except Telethon2FA:
            s["step"] = "temp_2fa"; await event.respond("🔐 رمز 2FA:")
    elif step == "temp_2fa":
        await s["client"].sign_in(password=text)
        s["raw_session"] = s["client"].session.save(); await show_main_menu(event)

    elif step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"; await event.respond("🔗 أرسل المعرف الهدف:", buttons=[[Button.inline("🔙 رجوع", b"transfer_menu")]])
    elif step == "target":
        s.update({"target": text, "running": True})
        s["status"] = await event.respond("🚀 جاري البدء...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))
    elif step == "steal_link":
        s.update({"source": text, "target": "me", "running": True})
        s["status"] = await event.respond("⚡ جاري السرقة...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))

@bot.on(events.CallbackQuery)
async def cb_handler(event):
    uid = event.sender_id; s = state.setdefault(uid, {}); d = event.data
    if d == b"main_menu": await show_main_menu(event)
    elif d == b"transfer_menu": await show_transfer_menu(event)
    elif d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل الرقم:")
    elif d == b"extract_session": s["step"] = "ex_phone"; await event.respond("🔑 أرسل الرقم:")
    elif d == b"clear_temp":
        if "client" in s:
            try: await s["client"].log_out()
            except: pass
            del s["client"]
        s["step"] = None; await event.edit("✅ تم الخروج من الحساب المؤقت.")
    elif d == b"sessions":
        wait_msg = await event.edit("🔍 جاري جلب الحسابات...")
        accs = await get_accounts()
        if not accs:
            await wait_msg.edit("❌ لا توجد حسابات.", buttons=[[Button.inline("🔙 رجوع", b"back_start")]])
            return
        btns = [[Button.inline(f"👤 {n}", f"load_{k}".encode())] for k, n in accs]
        btns.append([Button.inline("🔙 رجوع", b"back_start")])
        await wait_msg.edit("🛡 اختر الحساب:", buttons=btns)
    elif d == b"back_start":
        await event.edit("📟 النظام:", buttons=[[Button.inline("🛡 الحسابات", b"sessions")],[Button.inline("📲 دخول مؤقت", b"temp")],[Button.inline("🔑 استخراج", b"extract_session")],[Button.inline("🧹 خروج المؤقت", b"clear_temp")]])
    elif d.startswith(b"load_"):
        key = d.decode().replace("load_", "")
        s["raw_session"] = os.environ[key]
        s["client"] = TelegramClient(StringSession(s["raw_session"]), API_ID, API_HASH)
        await s["client"].connect(); await show_main_menu(event)
    elif d == b"new_transfer":
        s.update({"mode": "normal", "step": "delay", "sent": 0})
        await event.edit("⏱️ أرسل التأخير بالثواني:")
    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0})
        await event.edit("⚡ أرسل رابط/معرف المصدر:")
    elif d == b"stop": s["running"] = False; await event.answer("🛑 توقف")
    elif d == b"reset": s.update({"sent": 0}); await event.answer("🗑️ تم التصفير")

async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل", b"transfer_menu")], [Button.inline("⚡ السرقة", b"steal")]]
    await (event.edit if isinstance(event, events.CallbackQuery) else event.respond)("✅ خيارات الحساب:", buttons=btns)

async def show_transfer_menu(event):
    btns = [[Button.inline("📝 ابدأ نقل عادي", b"new_transfer")],[Button.inline("🗑️ تصفير العداد", b"reset"), Button.inline("🔙 رجوع", b"main_menu")]]
    await event.edit("📤 قائمة النقل:", buttons=btns)

bot.run_until_disconnected()
