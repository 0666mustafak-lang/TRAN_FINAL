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
            try: return set(map(int, f.read().splitlines()))
            except: return set()
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

def save_channels():
    with open(CHANNELS_FILE, "w") as f:
        json.dump(RECENT_CHANNELS, f, indent=2)

RECENT_CHANNELS = load_channels()
MAX_RECENT = 7

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
                async with TelegramClient(StringSession(os.environ[k]), API_ID, API_HASH) as c:
                    me = await c.get_me()
                    accs.append((k, me.first_name or me.username or "NoName"))
            except: pass
    return accs

async def show_main_menu(event):
    await event.respond(
        "✨ اختر العملية المطلوبة:",
        buttons=[
            [Button.inline("📤 قائمة النقل", b"transfer_menu")],
            [Button.inline("⚡ سرقة عادية", b"steal")],
            [Button.inline("🔓 سرقة محمية", b"steal_protected")]
        ]
    )

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
        else:
            await event.respond("🔐 أرسل رمز الدخول")
        return

    if text == "/start":
        s.clear()
        await event.respond(
            "طريقة الدخول:",
            buttons=[
                [Button.inline("🛡️ الحسابات المحمية", b"sessions")],
                [Button.inline("📲 دخول مؤقت", b"temp")],
                [Button.inline("🧹 تنظيف الجلسات", b"clear_temp")]
            ]
        )
        return

    step = s.get("step")

    # ===== حل مشكلة صفنة الرقم (طلب الكود في خلفية الكود) =====
    if step == "temp_phone":
        await event.respond("⏳ جاري طلب الكود من تليجرام...")
        
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = c
        
        try:
            await c.connect()
            sent = await c.send_code_request(text)
            s.update({"client": c, "phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
            await event.respond("✅ أرسل كود التحقق الآن:")
        except Exception as e:
            await event.respond(f"❌ فشل: {e}")
        return

    if step == "temp_code":
        try:
            await s["client"].sign_in(phone=s["phone"], code=text, phone_code_hash=s["hash"])
            s["step"] = "main"
            await show_main_menu(event)
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"
            await event.respond("🔐 أرسل رمز 2FA:")
        except Exception as e:
            await event.respond(f"❌ خطأ: {e}")
        return

    if step == "temp_2fa":
        try:
            await s["client"].sign_in(password=text)
            s["step"] = "main"
            await show_main_menu(event)
        except Exception as e:
            await event.respond(f"❌ خطأ: {e}")
        return

    # ===== INPUTS =====
    if step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"
        await event.respond("🔗 أرسل معرف الهدف:")
        return

    if step == "target" or step == "steal_link":
        if step == "steal_link": s["source"] = text
        else: s["target"] = text
        s["running"] = True
        s["status"] = await event.respond("🚀 بدء العمل...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run(uid))
        return

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb(event):
    await event.answer()
    uid = event.sender_id
    s = state.setdefault(uid, {})
    d = event.data

    if d == b"sessions":
        accs = await get_accounts()
        if not accs: await event.respond("❌ لا توجد حسابات")
        else: await event.respond("🛡️ اختر حسابك:", buttons=[[Button.inline(n, k.encode())] for k, n in accs])
        s["step"] = "choose_session"
    elif d == b"temp":
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل الرقم")
    elif d == b"transfer_menu":
        await event.respond("قائمة النقل:", buttons=[
            [Button.inline("📤 نقل فردي", b"new_transfer")],
            [Button.inline("📦 نقل تجميعي", b"batch_transfer")],
            [Button.inline("▶️ استكمال", b"resume")],
            [Button.inline("🗑️ مسح الذاكرة", b"reset")]
        ])
    elif d == b"new_transfer":
        s.update({"mode": "transfer", "step": "delay", "last_id": 0, "sent": 0})
        await event.respond("⏱️ أرسل التأخير")
    elif d == b"batch_transfer":
        s.update({"mode": "batch_transfer", "step": "delay", "last_id": 0, "sent": 0})
        await event.respond("⏱️ أرسل التأخير")
    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "last_id": 0, "sent": 0})
        await event.respond("🔗 أرسل رابط المصدر")
    elif d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link", "last_id": 0, "sent": 0})
        await event.respond("🔓 أرسل رابط المصدر (المحمي)")
    elif d == b"stop":
        s["running"] = False
    elif d == b"clear_temp":
        for c in TEMP_SESSIONS.values(): 
            try: await c.log_out()
            except: pass
        TEMP_SESSIONS.clear()
        await event.respond("🧹 تم التنظيف")

# ================= RUN LOGIC =================
async def run(uid):
    s = state[uid]
    c = s["client"]
    try:
        if s["mode"].startswith("steal"):
            src = await c.get_entity(s["source"])
            dst = "me"
        else:
            src = await c.get_entity("me")
            dst = await c.get_entity(s["target"])

        batch = []
        async for m in c.iter_messages(src, offset_id=s.get("last_id", 0), reverse=True):
            if not s["running"]: break
            if not m.video: continue

            if s["mode"] == "batch_transfer":
                batch.append(m.video)
                s["last_id"] = m.id
                if len(batch) == 10:
                    await c.send_file(dst, batch)
                    s["sent"] += 10
                    await s["status"].edit(f"📦 تجميعي: {s['sent']}")
                    batch.clear()
                    await asyncio.sleep(5)
                continue

            await c.send_file(dst, m.video, caption=clean_caption(m.text))
            s["last_id"] = m.id
            s["sent"] += 1
            await s["status"].edit(f"📊 نقل: {s['sent']}")
            
            if s["mode"] == "transfer":
                RECENT_CHANNELS[:] = [x for x in RECENT_CHANNELS if x["target"] != s["target"]]
                RECENT_CHANNELS.insert(0, {"title": "Target", "target": s["target"], "last_id": s["last_id"], "sent": s["sent"]})
                save_channels()
            
            await asyncio.sleep(s.get("delay", 10))

        if batch: await c.send_file(dst, batch)
        await s["status"].edit("✅ اكتمل!")
    except Exception as e:
        await bot.send_message(uid, f"❌ فشل: {e}")

bot.run_until_disconnected()
