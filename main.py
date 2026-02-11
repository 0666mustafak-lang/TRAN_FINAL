import asyncio
import os
import re
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from pyrogram import Client as PyroClient, enums

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
TEMP_SESSIONS = {}

def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_accounts():
    accs = []
    for k in sorted(os.environ.keys()):
        if not k.startswith("TG_SESSION_"): continue
        accs.append((k, k.replace("TG_SESSION_", "")))
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
            with open(AUTH_FILE, "a") as f: f.write(f"{uid}\n")
            await event.respond("✅ تم الدخول، أرسل /start")
        else: await event.respond("🔐 أرسل رمز الدخول")
        return

    if text == "/start":
        s.clear()
        await event.respond("📟 **مرحباً بك**", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج سيشن", b"extract_session")],
            [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")] # رجع الزر هنا
        ])
        return

    step = s.get("step")
    if step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = c
        await c.connect()
        try:
            sent = await c.send_code_request(text)
            s.update({"client": c, "phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
            await event.respond("🔑 أرسل كود التحقق")
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
    elif step == "temp_code":
        try:
            await s["client"].sign_in(phone=s["phone"], code=text, phone_code_hash=s["hash"])
            s["raw_session"] = s["client"].session.save()
            s["step"] = "main"; await show_main_menu(event)
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"; await event.respond("🔐 أرسل رمز 2FA")
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
    elif step == "temp_2fa":
        try:
            await s["client"].sign_in(password=text)
            s["raw_session"] = s["client"].session.save()
            s["step"] = "main"; await show_main_menu(event)
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
    elif step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"; await event.respond("🔗 أرسل الهدف")
    elif step == "target":
        s["target"] = text; s["running"] = True
        s["status"] = await event.respond("🚀 بدء العملية...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))
    elif step == "steal_link":
        s["source"] = text; s["target"] = "me"; s["running"] = True
        s["status"] = await event.respond("⚡ بدء السرقة...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb(event):
    uid = event.sender_id
    s = state.setdefault(uid, {})
    d = event.data

    if d == b"sessions":
        accs = await get_accounts()
        btns = [[Button.inline(n, f"load_{k}".encode())] for k, n in accs]
        await event.edit("🛡 الحسابات:", buttons=btns)
    elif d.startswith(b"load_"):
        sess_key = d.decode().replace("load_", "")
        s["raw_session"] = os.environ[sess_key]
        s["client"] = TelegramClient(StringSession(s["raw_session"]), API_ID, API_HASH)
        await s["client"].connect()
        await show_main_menu(event)
    elif d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل الرقم")
    elif d == b"clear_temp": # وظيفة تسجيل الخروج
        if uid in TEMP_SESSIONS:
            try: await TEMP_SESSIONS[uid].log_out()
            except: pass
            del TEMP_SESSIONS[uid]
        s.clear()
        await event.respond("🧹 تم تسجيل الخروج ومسح الجلسة.")
    elif d == b"transfer_menu": await show_transfer_menu(event)
    elif d in [b"new_transfer", b"batch_transfer"]:
        s.update({"mode": "transfer" if d == b"new_transfer" else "batch_transfer", "step": "delay", "sent": 0, "last_id": 0})
        await event.respond("⏱️ أرسل التأخير:")
    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0, "delay": 0, "last_id": 0})
        await event.respond("🔗 أرسل المصدر:")
    elif d == b"clean_menu":
        if not s.get("raw_session"): await event.respond("❌ سجل دخول أولاً"); return
        lmsg = await event.respond("🔍 جاري فحص القنوات...")
        async with PyroClient(f"p_{uid}", API_ID, API_HASH, session_string=s["raw_session"]) as pc:
            btns = []
            async for dialog in pc.get_dialogs():
                if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]:
                    try:
                        m = await pc.get_chat_member(dialog.chat.id, "me")
                        if m.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                            btns.append([Button.inline(f"🧹 {dialog.chat.title[:20]}", f"pclean_{dialog.chat.id}".encode())])
                    except: continue
            await lmsg.edit("✅ اختر لتنظيفه:", buttons=btns)
    elif d.startswith(b"pclean_"):
        chat_id = int(d.decode().split("_")[1])
        asyncio.create_task(run_cleaning(event, chat_id, s["raw_session"]))
    elif d == b"stop": s["running"] = False
    elif d == b"reset": s.update({"last_id": 0, "sent": 0}); await event.answer("🗑️ تم التصفير")

# ================= MENUS =================
async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل", b"transfer_menu")], [Button.inline("⚡ السرقة", b"steal")]]
    await event.respond("✅ القائمة الرئيسية:", buttons=btns) if not isinstance(event, events.CallbackQuery) else await event.edit("✅ القائمة الرئيسية:", buttons=btns)

async def show_transfer_menu(event):
    await event.edit("📤 قائمة النقل:", buttons=[
        [Button.inline("📝 نقل عادي (وصف)", b"new_transfer")],
        [Button.inline("📦 نقل تجميعي (10/10)", b"batch_transfer")],
        [Button.inline("🧹 تنظيف الإدمن", b"clean_menu")],
        [Button.inline("🗑️ إعادة ضبط", b"reset")]
    ])

# ================= ENGINES =================
async def run_engine(uid):
    s = state[uid]; client = s["client"]; mode = s["mode"]; delay = s["delay"]
    src = await client.get_entity(s.get("source", "me")); dst = s.get("target", "me")
    
    msgs = await client.get_messages(src, limit=0)
    total = msgs.total
    batch = []

    async for m in client.iter_messages(src, offset_id=s.get("last_id", 0), limit=None):
        if not s.get("running"): break
        if not m.video: continue

        if mode in ["batch_transfer", "steal"]:
            batch.append(m)
            if len(batch) == 10:
                await client.send_file(dst, batch)
                s["sent"] += 10; s["last_id"] = m.id; batch.clear()
                await s["status"].edit(f"📊 {mode}: {s['sent']} / {total}")
                if delay > 0 and mode == "batch_transfer": await asyncio.sleep(delay)
        else:
            await client.send_file(dst, m, caption=clean_caption(m.text))
            s["sent"] += 1; s["last_id"] = m.id
            await s["status"].edit(f"📊 نقل عادي: {s['sent']} / {total}")
            if delay > 0: await asyncio.sleep(delay)

    if batch and s.get("running"): await client.send_file(dst, batch); s["sent"] += len(batch)
    await s["status"].edit(f"✅ اكتمل: {s['sent']} / {total}")

async def run_cleaning(event, chat_id, sess):
    status = await event.respond("🔄 جاري التنظيف...")
    async with PyroClient(f"c_{event.sender_id}", API_ID, API_HASH, session_string=sess) as pc:
        s_ids = [m.id async for m in pc.get_chat_history(chat_id, limit=500) if m.service]
        if s_ids:
            for i in range(0, len(s_ids), 100): await pc.delete_messages(chat_id, s_ids[i:i+100])
        
        b_count = 0
        async for member in pc.get_chat_members(chat_id):
            if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                try:
                    await pc.ban_chat_member(chat_id, member.user.id); b_count += 1
                    if b_count % 5 == 0: await status.edit(f"📊 طرد: {b_count}")
                    await asyncio.sleep(2)
                except: continue
        await status.edit(f"✅ تم التنظيف بنجاح.")

bot.run_until_disconnected()
