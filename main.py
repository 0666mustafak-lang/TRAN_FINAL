import os
import asyncio
import re
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# ================= CONFIG =================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"

def load_authorized():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE) as f:
            try: return set(map(int, f.read().splitlines()))
            except: return set()
    return set()

AUTHORIZED_USERS = load_authorized()

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}

def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_accounts():
    accs = []
    for k in sorted(os.environ.keys()):
        if not k.startswith("TG_SESSION_"): continue
        accs.append((k, k.replace("TG_SESSION_", "")))
    return accs

# ================= MENUS =================
async def show_main_menu(event):
    btns = [
        [Button.inline("📤 النقل", b"transfer_menu")],
        [Button.inline("⚡ السرقة", b"steal"), Button.inline("🔓 السرقة المحمية", b"steal_protected")]
    ]
    if isinstance(event, events.CallbackQuery): await event.edit("✅ خيارات الحساب:", buttons=btns)
    else: await event.respond("✅ خيارات الحساب:", buttons=btns)

async def show_transfer_menu(event):
    btns = [
        [Button.inline("📝 عادي", b"new_transfer"), Button.inline("⏯️ استكمال", b"resume_normal")],
        [Button.inline("📦 تجميعي", b"batch_transfer"), Button.inline("⏯️ استكمال", b"resume_batch")],
        [Button.inline("🗑️ ضبط", b"reset"), Button.inline("🔙 رجوع", b"main_menu")]
    ]
    await event.edit("📤 قائمة النقل:", buttons=btns)

# ================= MESSAGE ROUTER =================
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
        await event.respond("📟 **نظام التحكم الأصلي**", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج سيشن (جديد)", b"extract_session")],
            [Button.inline("🧹 خروج المؤقت", b"clear_temp")]
        ])
        return

    step = s.get("step")
    
    if step == "temp_phone":
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
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"; await event.respond("🔐 رمز 2FA:")
    elif step == "temp_2fa":
        await s["client"].sign_in(password=text)
        s["raw_session"] = s["client"].session.save(); await show_main_menu(event)

    elif step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"; await event.respond("🔗 أرسل المعرف الهدف:", buttons=[[Button.inline("🔙 رجوع", b"transfer_menu")]])
    elif step == "target":
        s.update({"target": text, "running": True})
        s["status"] = await event.respond("🚀 جاري فحص الرسائل والبدء...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))
    elif step == "steal_link":
        s.update({"source": text, "target": "me", "running": True})
        s["status"] = await event.respond("⚡ جاري البدء بالسرقة...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb_handler(event):
    uid = event.sender_id; s = state.setdefault(uid, {}); d = event.data

    if d == b"main_menu": await show_main_menu(event)
    elif d == b"transfer_menu": await show_transfer_menu(event)
    elif d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل الرقم:")
    
    elif d == b"sessions":
        accs = await get_accounts()
        btns = [[Button.inline(n, f"load_{k}".encode())] for k, n in accs]
        btns.append([Button.inline("🔙 رجوع", b"back_start")])
        await event.edit("🛡 اختر الحساب:", buttons=btns)
    elif d == b"back_start":
        await event.edit("📟 النظام:", buttons=[[Button.inline("🛡 الحسابات", b"sessions")],[Button.inline("📲 دخول مؤقت", b"temp")]])

    elif d.startswith(b"load_"):
        key = d.decode().replace("load_", "")
        s["raw_session"] = os.environ[key]
        s["client"] = TelegramClient(StringSession(s["raw_session"]), API_ID, API_HASH)
        await s["client"].connect(); await show_main_menu(event)

    elif d in [b"new_transfer", b"batch_transfer"]:
        s.update({"mode": "normal" if d == b"new_transfer" else "batch", "step": "delay", "sent": 0, "last_id": 0})
        await event.edit("⏱️ أرسل وقت التأخير:", buttons=[[Button.inline("🔙 رجوع", b"transfer_menu")]])
    
    elif d in [b"resume_normal", b"resume_batch"]:
        s.update({"mode": "normal" if d == b"resume_normal" else "batch", "step": "delay"})
        await event.edit(f"⏯️ استكمال من {s.get('sent', 0)}.. أرسل التأخير:", buttons=[[Button.inline("🔙 رجوع", b"transfer_menu")]])

    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0, "last_id": 0})
        await event.edit("⚡ أرسل المصدر للسرقة:", buttons=[[Button.inline("🔙 رجوع", b"main_menu")]])

    elif d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link", "sent": 0, "last_id": 0})
        await event.edit("🔓 أرسل المصدر المحمي:", buttons=[[Button.inline("🔙 رجوع", b"main_menu")]])

    elif d == b"stop": s["running"] = False; await event.answer("🛑 توقف")
    elif d == b"reset": s.update({"sent": 0, "last_id": 0}); await event.answer("🗑️ تم التصفير")

# ================= ENGINE =================
async def run_engine(uid):
    s = state[uid]; client = s["client"]; mode = s["mode"]
    src = s.get("source", "me"); dst = s.get("target", "me")
    
    m_info = await client.get_messages(src, limit=0)
    total = m_info.total
    batch = []
    
    async for m in client.iter_messages(src, offset_id=s.get("last_id", 0), reverse=True):
        if not s.get("running"): break
        if not m.video: continue

        if mode in ["batch", "steal", "steal_protected"]:
            batch.append(m)
            if len(batch) == 10:
                await client.send_file(dst, batch); s["sent"] += 10; s["last_id"] = m.id; batch.clear()
                await s["status"].edit(f"📊 Progress: {s['sent']} / {total}")
                if mode == "batch": await asyncio.sleep(s["delay"])
        else:
            await client.send_file(dst, m, caption=clean_caption(m.text))
            s["sent"] += 1; s["last_id"] = m.id
            await s["status"].edit(f"📊 Progress: {s['sent']} / {total}")
            await asyncio.sleep(s["delay"])
            
    if batch and s.get("running"): 
        await client.send_file(dst, batch); s["sent"] += len(batch)
    await s["status"].edit(f"✅ اكتملت العملية: {s['sent']} / {total}")

bot.run_until_disconnected()
