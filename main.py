import asyncio
import os
import re
import json
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

# ================= AUTH =================
def load_authorized():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE) as f:
            return set(map(int, f.read().splitlines()))
    return set()

def save_authorized(uid):
    with open(AUTH_FILE, "a") as f:
        f.write(f"{uid}\n")

AUTHORIZED_USERS = load_authorized()

# ================= CHANNEL MEMORY =================
def load_channels():
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE) as f:
            try: return json.load(f)
            except: return []
    return []

RECENT_CHANNELS = load_channels()
MAX_RECENT = 7

def save_channels():
    with open(CHANNELS_FILE, "w") as f:
        json.dump(RECENT_CHANNELS, f, indent=2)

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}
TEMP_SESSIONS = {}

# ================= HELPERS =================
def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_accounts():
    accs = []
    for k in sorted(os.environ.keys()):
        if k.startswith("TG_SESSION_"):
            try:
                # فحص سريع بدون انتظار طويل
                c = TelegramClient(StringSession(os.environ[k]), API_ID, API_HASH)
                await c.connect()
                me = await c.get_me()
                accs.append((k, me.first_name or "Account"))
                await c.disconnect()
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
        s.clear()
        await event.respond("اختر طريقة الدخول:", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
        ])
        return

    step = s.get("step")
    if step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        await c.connect()
        sent = await c.send_code_request(text)
        s.update({"client": c, "phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
        await event.respond("🔑 أرسل كود التحقق:")
    elif step == "temp_code":
        try:
            await s["client"].sign_in(s["phone"], text, phone_code_hash=s["hash"])
            await show_main_menu(event)
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"
            await event.respond("🔐 أرسل رمز 2FA:")
    elif step == "temp_2fa":
        await s["client"].sign_in(password=text)
        await show_main_menu(event)
    elif step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"
        await event.respond("🔗 أرسل معرف القناة الهدف:")
    elif step == "target":
        s.update({"target": text, "running": True})
        s["status"] = await event.respond("🚀 بدء النقل...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run(uid))
    elif step == "steal_link":
        s.update({"source": text, "running": True})
        s["status"] = await event.respond("⚡ بدء السرقة...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run(uid))

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb(event):
    uid = event.sender_id
    s = state.setdefault(uid, {})
    d = event.data

    if d == b"sessions":
        accs = await get_accounts()
        if not accs: await event.respond("❌ لا توجد حسابات في Variables"); return
        btns = [[Button.inline(n, f"load_{k}".encode())] for k, n in accs]
        await event.edit("🛡 اختر الحساب:", buttons=btns)
    elif d.startswith(b"load_"):
        key = d.decode().split("_")[1]
        s["client"] = TelegramClient(StringSession(os.environ[key]), API_ID, API_HASH)
        await s["client"].connect()
        await show_main_menu(event)
    elif d == b"temp":
        s["step"] = "temp_phone"
        await event.edit("📲 أرسل رقم الهاتف:")
    elif d == b"clear_temp":
        if "client" in s: await s["client"].log_out()
        await event.answer("🧹 تم تسجيل الخروج")
    elif d == b"transfer_menu": await show_transfer_menu(event)
    elif d == b"new_transfer":
        s.update({"mode": "transfer", "step": "delay", "last_id": 0, "sent": 0})
        await event.edit("⏱️ أرسل التأخير (بالثواني):")
    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "last_id": 0, "sent": 0})
        await event.edit("🔗 أرسل رابط المصدر:")
    elif d == b"stop": s["running"] = False; await event.answer("🛑 تم الإيقاف")

async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل", b"transfer_menu")], [Button.inline("⚡ السرقة (10+10)", b"steal")]]
    await (event.edit if isinstance(event, events.CallbackQuery) else event.respond)("اختر العملية:", buttons=btns)

async def show_transfer_menu(event):
    btns = [[Button.inline("📤 نقل جديد", b"new_transfer")], [Button.inline("🔙 رجوع", b"main_menu")]]
    await event.edit("قائمة النقل:", buttons=btns)

# ================= THE CORE RUNNER =================
async def run(uid):
    s = state[uid]; c = s["client"]
    try:
        if s["mode"] == "transfer":
            src = "me"
            dst = s["target"]
        else:
            src = s["source"]
            dst = "me"

        batch = []; s["sent"] = 0
        # جلب الرسائل بالترتيب من الأقدم للأحدث لنقل منطقي
        async for m in c.iter_messages(src, min_id=s.get("last_id", 0), reverse=True):
            if not s.get("running"): break
            if not m.media: continue

            # --- نظام السرقة (تجميع 10) ---
            if s["mode"] == "steal":
                batch.append(m.media)
                if len(batch) == 10:
                    await c.send_file(dst, batch, caption="")
                    s["sent"] += 10
                    await s["status"].edit(f"📊 سرقة: {s['sent']}")
                    batch = []
                    await asyncio.sleep(1)
                continue

            # --- نظام النقل (فيديو فيديو) ---
            await c.send_file(dst, m.media, caption=clean_caption(m.text))
            s["sent"] += 1
            await s["status"].edit(f"📊 نقل: {s['sent']}")
            await asyncio.sleep(s.get("delay", 5))

        if batch: # إرسال المتبقي
            await c.send_file(dst, batch, caption="")
            s["sent"] += len(batch)
            await s["status"].edit(f"📊 سرقة: {s['sent']}")

        await s["status"].edit(f"✅ انتهى! الإجمالي: {s['sent']}")
    except Exception as e:
        await s["status"].edit(f"❌ خطأ: {str(e)}")

bot.run_until_disconnected()
