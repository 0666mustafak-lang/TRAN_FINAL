import asyncio
import os
import re
import json
import random
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# ================= CONFIG =================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"
CHANNELS_FILE = "saved_channels.json"

# ================= AUTH & MEMORY =================
def load_authorized():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE) as f:
            return set(map(int, f.read().splitlines()))
    return set()

def save_authorized(uid):
    with open(AUTH_FILE, "a") as f:
        f.write(f"{uid}\n")

AUTHORIZED_USERS = load_authorized()

def load_channels():
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE) as f:
            return json.load(f)
    return []

RECENT_CHANNELS = load_channels()
MAX_RECENT = 7

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}

def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_accounts():
    accs = []
    for k in sorted(os.environ.keys()):
        if k.startswith("TG_SESSION_"):
            try:
                async with TelegramClient(StringSession(os.environ[k]), API_ID, API_HASH) as c:
                    me = await c.get_me()
                    accs.append((k, me.first_name or "NoName"))
            except: continue
    return accs

# ================= MESSAGE ROUTER =================
@bot.on(events.NewMessage)
async def router(event):
    uid = event.sender_id
    text = (event.text or "").strip()
    s = state.setdefault(uid, {})

    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            AUTHORIZED_USERS.add(uid)
            save_authorized(uid)
            await event.respond("✅ تم التفعيل، أرسل /start")
        else: await event.respond("🔐 أرسل رمز الدخول")
        return

    if text == "/start":
        await event.respond("اختر طريقة الدخول:", buttons=[
            [Button.inline("🛡 الحسابات (Session)", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🧹 خروج المؤقت", b"clear_temp")]
        ])
        return

    step = s.get("step")
    if step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH); s["client"] = c; await c.connect()
        sent = await c.send_code_request(text)
        s.update({"phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
        await event.respond("🔑 أرسل كود التحقق")
    elif step == "temp_code":
        try:
            await s["client"].sign_in(phone=s["phone"], code=text, phone_code_hash=s["hash"])
            await show_main_menu(event)
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"; await event.respond("🔐 أرسل رمز 2FA")
    elif step == "temp_2fa":
        await s["client"].sign_in(password=text); await show_main_menu(event)
    elif step == "target":
        s.update({"target": text, "running": True})
        s["status"] = await event.respond("🚀 بدء النقل...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))
    elif step == "steal_link":
        s.update({"source": text, "running": True})
        s["status"] = await event.respond("⚡ بدء السرقة السريعة...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb(event):
    uid = event.sender_id; s = state.setdefault(uid, {}); d = event.data
    if d == b"sessions":
        accs = await get_accounts()
        if not accs: return await event.respond("❌ لا توجد حسابات")
        btns = [[Button.inline(n, k.encode())] for k, n in accs]
        await event.respond("🛡 اختر الحساب:", buttons=btns); s["step"] = "choose_session"
    elif s.get("step") == "choose_session":
        s["client"] = TelegramClient(StringSession(os.environ[d.decode()]), API_ID, API_HASH)
        await s["client"].connect(); await show_main_menu(event)
    elif d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل الرقم")
    elif d == b"transfer_menu": await show_transfer_menu(event)
    elif d in [b"new_transfer", b"batch_transfer"]:
        s["mode"] = "transfer" if d == b"new_transfer" else "batch"
        s["sent"] = 0; s["last_id"] = 0
        await event.edit("⏱️ اختر نوع التأخير للنقل:", buttons=[
            [Button.inline("⏱️ ثابت (10 ثواني)", b"set_delay_10")],
            [Button.inline("🎲 متغير (10-19 ثانية)", b"set_delay_rnd")]
        ])
    elif d.startswith(b"set_delay_"):
        s["delay_type"] = "fixed" if d == b"set_delay_10" else "random"
        s["step"] = "target"; await event.edit("🔗 أرسل المعرف الهدف (أو me):")
    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0, "last_id": 0})
        await event.edit("⚡ أرسل رابط القناة المصدر:")
    elif d == b"stop": s["running"] = False; await event.answer("⏹️ توقف")
    elif d == b"reset": RECENT_CHANNELS.clear(); await event.answer("🗑️ تم التصفير")

# ================= MENUS =================
async def show_main_menu(event):
    await event.respond("اختر العملية:", buttons=[
        [Button.inline("📤 النقل", b"transfer_menu")],
        [Button.inline("⚡ السرقة", b"steal")]
    ])

async def show_transfer_menu(event):
    await event.respond("قائمة النقل:", buttons=[
        [Button.inline("📤 نقل فردي", b"new_transfer")],
        [Button.inline("📦 نقل تجميعي", b"batch_transfer")],
        [Button.inline("🗑️ إعادة ضبط", b"reset")]
    ])

# ================= ENGINE (الدمج الاحترافي) =================
async def run_engine(uid):
    s = state[uid]; c = s["client"]
    
    # تحديد المصدر والهدف بناءً على الوضع
    if s["mode"] in ["transfer", "batch"]:
        src = await c.get_entity("me")
        dst = await c.get_entity(s["target"])
    else: # نظام السرقة
        src = await c.get_entity(s["source"])
        dst = await c.get_entity("me")

    batch = []
    # استخدام min_id من الكود القديم لضمان الاستقرار
    async for m in c.iter_messages(src, min_id=s.get("last_id", 0), reverse=True):
        if not s.get("running"): break
        if not m.media: continue

        try:
            # نظام السرقة أو التجميعي (سريع)
            if s["mode"] in ["steal", "batch"]:
                batch.append(m.media)
                if len(batch) == 10:
                    await c.send_file(dst, batch)
                    s["sent"] += 10; s["last_id"] = m.id; batch.clear()
                    await s["status"].edit(f"📊 تم نقل: {s['sent']}")
                    # تأخير فقط في التجميعي (Batch)، السرقة بدون تأخير
                    if s["mode"] == "batch":
                        wait = 10 if s.get("delay_type") == "fixed" else random.randint(10, 19)
                        await asyncio.sleep(wait)
            
            # نظام النقل الفردي (المستقر)
            else:
                await c.send_file(dst, m.media, caption=clean_caption(m.text))
                s["sent"] += 1; s["last_id"] = m.id
                await s["status"].edit(f"📊 تم نقل: {s['sent']}")
                wait = 10 if s.get("delay_type") == "fixed" else random.randint(10, 19)
                await asyncio.sleep(wait)

        except Exception as e:
            if "FloodWait" in str(e):
                await asyncio.sleep(int(re.findall(r'\d+', str(e))[0]))
            continue

    if batch and s.get("running"):
        await c.send_file(dst, batch); s["sent"] += len(batch)
        await s["status"].edit(f"📊 تم نقل: {s['sent']}")

    await s["status"].edit(f"✅ اكتمل العمل: {s['sent']}")

bot.run_until_disconnected()
