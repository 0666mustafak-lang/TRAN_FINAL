import asyncio
import os
import re
import json
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError

# ================= CONFIG =================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"

def load_authorized():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE) as f:
            return set(map(int, f.read().splitlines()))
    return set()

AUTHORIZED_USERS = load_authorized()
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}

def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_accounts():
    accs = []
    for k in sorted(os.environ.keys()):
        if k.startswith("TG_SESSION_"):
            accs.append((k, k.replace("TG_SESSION_", "")))
    return accs

# ================= ROUTER =================
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
        return

    if text == "/start":
        s.clear()
        await event.respond("📟 لوحة التحكم:", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
        ])
        return

    step = s.get("step")
    if step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH); await c.connect()
        sent = await c.send_code_request(text)
        s.update({"client": c, "phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
        await event.respond("🔑 الكود:")
    elif step == "temp_code":
        try:
            await s["client"].sign_in(s["phone"], text, phone_code_hash=s["hash"])
            await show_main_menu(event)
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"; await event.respond("🔐 رمز 2FA:")
    elif step == "temp_2fa":
        await s["client"].sign_in(password=text); await show_main_menu(event)
    elif step == "delay":
        s["delay"] = int(text) if text.isdigit() else 20
        s["step"] = "target"; await event.respond("🔗 أرسل معرف القناة الهدف:")
    elif step == "target":
        s.update({"target": text, "running": True})
        s["status"] = await event.respond("🚀 جاري البدء...", buttons=[[Button.inline("🛑 إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))
    elif step == "steal_link":
        s.update({"source": text, "running": True})
        s["status"] = await event.respond("⚡ جاري السرقة...", buttons=[[Button.inline("🛑 إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb_handler(event):
    uid = event.sender_id; s = state.setdefault(uid, {}); d = event.data
    if d == b"sessions":
        accs = await get_accounts()
        btns = [[Button.inline(f"👤 {n}", f"load_{k}".encode())] for k, n in accs]
        await event.edit("🛡 اختر الحساب:", buttons=btns)
    elif d.startswith(b"load_"):
        key = d.decode().split("_", 1)[1]
        s["client"] = TelegramClient(StringSession(os.environ[key]), API_ID, API_HASH)
        await s["client"].connect(); await show_main_menu(event)
    elif d == b"temp":
        s["step"] = "temp_phone"; await event.edit("📲 أرسل رقم الهاتف:")
    elif d == b"clear_temp":
        if "client" in s: await s["client"].disconnect(); s.pop("client")
        await event.answer("🧹 تم تسجيل الخروج")
    elif d == b"transfer_menu":
        s.update({"mode": "transfer", "step": "delay", "sent": 0})
        await event.edit("⏱️ كم ثانية تأخير؟ (يفضل 20):")
    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0})
        await event.edit("⚡ أرسل رابط المصدر (10+10):")
    elif d == b"stop":
        s["running"] = False; await event.answer("🛑 توقف")

async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل (محفوظات -> هدف)", b"transfer_menu")], [Button.inline("⚡ السرقة (مصدر -> محفوظات)", b"steal")]]
    await (event.edit if isinstance(event, events.CallbackQuery) else event.respond)("✅ اختر العملية:", buttons=btns)

# ================= ENGINE (ZERO WAIT) =================
async def run_engine(uid):
    s = state[uid]; client = s["client"]; mode = s["mode"]
    src = "me" if mode == "transfer" else s.get("source")
    dst = s.get("target") if mode == "transfer" else "me"
    batch = []; s["sent"] = 0
    
    try:
        m_info = await client.get_messages(src, limit=0)
        total = m_info.total
    except: total = "???"

    async for m in client.iter_messages(src, reverse=True):
        if not s.get("running"): break
        if not m.media: continue

        try:
            if mode == "steal":
                batch.append(m.media)
                if len(batch) == 10:
                    await client.send_file(dst, batch, caption="")
                    s["sent"] += 10
                    await s["status"].edit(f"⚡ سرقة: {s['sent']} / {total}")
                    batch = []
            else:
                await client.send_file(dst, m.media, caption=clean_caption(m.text))
                s["sent"] += 1
                await s["status"].edit(f"📤 نقل: {s['sent']} / {total}")
                # التأخير اليدوي الذي تضعه أنت (مثلاً 20 ثانية)
                await asyncio.sleep(s.get("delay", 20))

        except FloodWaitError:
            # هنا التعديل: لا يوجد sleep نهائياً.
            # إذا رفض تليجرام الإرسال، انتقل فوراً للملف التالي.
            continue 
        except Exception:
            continue

    if batch and s.get("running"):
        try: await client.send_file(dst, batch, caption="")
        except: pass

    await s["status"].edit(f"✅ انتهى العمل.\n📦 الإجمالي: {s['sent']} / {total}")

bot.run_until_disconnected()
