import asyncio
import os
import re
import json
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
        try:
            async with TelegramClient(StringSession(os.environ[k]), API_ID, API_HASH) as c:
                me = await c.get_me()
                accs.append((k, me.first_name or me.username or "NoName"))
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
            with open(AUTH_FILE, "a") as f: f.write(f"{uid}\n")
            await event.respond("✅ تم الدخول، أرسل /start")
        else: await event.respond("🔐 أرسل رمز الدخول")
        return

    if text == "/start":
        s.clear()
        await event.respond("اختر طريقة الدخول:", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج سيشن", b"extract_session")],
            [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
        ])
        return

    step = s.get("step")
    
    # دخول مؤقت - رقم الهاتف
    if step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = c
        await c.connect()
        try:
            sent = await c.send_code_request(text)
            s.update({"client": c, "phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
            await event.respond("🔑 أرسل كود التحقق")
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
        return

    # دخول مؤقت - الكود
    if step == "temp_code":
        try:
            await s["client"].sign_in(phone=s["phone"], code=text, phone_code_hash=s["hash"])
            s["raw_session"] = s["client"].session.save()
            s["step"] = "main"; await show_main_menu(event)
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"; await event.respond("🔐 أرسل رمز 2FA")
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
        return

    if step == "temp_2fa":
        try:
            await s["client"].sign_in(password=text)
            s["raw_session"] = s["client"].session.save()
            s["step"] = "main"; await show_main_menu(event)
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
        return

    # النقل - طلب التأخير
    if step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"; await event.respond("🔗 أرسل الهدف")
        return

    if step == "target":
        s["target"] = text; s["running"] = True
        s["status"] = await event.respond("🚀 بدء العملية...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run(uid)); return

    if step == "steal_link":
        s["source"] = text; s["running"] = True
        s["status"] = await event.respond("⚡ بدء السرقة السريعة (10/10)...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run(uid)); return

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb(event):
    await event.answer()
    uid = event.sender_id
    s = state.setdefault(uid, {})
    d = event.data

    if d == b"sessions":
        accs = await get_accounts()
        if not accs: await event.respond("❌ لا توجد حسابات"); return
        btns = [[Button.inline(n, k.encode())] for k, n in accs]
        await event.respond("🛡 الحسابات:", buttons=btns)
        s["step"] = "choose_session"; return

    if s.get("step") == "choose_session":
        sess_str = os.environ[d.decode()]
        s["client"] = TelegramClient(StringSession(sess_str), API_ID, API_HASH)
        await s["client"].start()
        s["raw_session"] = sess_str
        s["step"] = "main"; await show_main_menu(event); return

    if d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل رقم الهاتف"); return
    
    if d == b"clear_temp":
        if uid in TEMP_SESSIONS:
            try: await TEMP_SESSIONS[uid].log_out()
            except: pass
            del TEMP_SESSIONS[uid]
        s.clear()
        await event.respond("🧹 تم تسجيل الخروج ومسح الجلسة. أرسل /start")
        return

    if d == b"transfer_menu": await show_transfer_menu(event); return
    
    if d == b"new_transfer" or d == b"batch_transfer":
        s.update({"mode": "transfer" if d == b"new_transfer" else "batch_transfer", "step": "delay", "last_id": 0, "sent": 0})
        await event.respond("⏱️ أرسل التأخير"); return

    if d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "last_id": 0, "sent": 0, "delay": 0})
        await event.respond("🔗 أرسل رابط القناة"); return
    
    if d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link", "last_id": 0, "sent": 0, "delay": 0})
        await event.respond("🔓 أرسل رابط القناة المحمية"); return

    if d == b"clean_menu":
        if not s.get("raw_session"): await event.respond("❌ سجل دخول أولاً"); return
        lmsg = await event.respond("🔍 فحص الحساب...")
        try:
            async with PyroClient(f"p_{uid}", API_ID, API_HASH, session_string=s["raw_session"]) as pc:
                btns = []
                async for d_ in pc.get_dialogs(limit=50):
                    if d_.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]:
                        try:
                            m = await pc.get_chat_member(d_.chat.id, "me")
                            if m.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                                btns.append([Button.inline(f"🧹 {d_.chat.title}", f"pclean_{d_.chat.id}".encode())])
                        except: continue
                if btns: await lmsg.edit("✅ اختر لتنظيفه:", buttons=btns)
                else: await lmsg.edit("❌ لا توجد قنوات إدمن")
        except Exception as e: await lmsg.edit(f"❌ خطأ: {e}")
        return

    if d == b"stop": s["running"] = False

# ================= MENUS =================
async def show_main_menu(event):
    await event.respond("اختر العملية:", buttons=[
        [Button.inline("📤 النقل", b"transfer_menu")],
        [Button.inline("⚡ السرقة", b"steal")],
        [Button.inline("🔓 السرقة المحمية", b"steal_protected")],
        [Button.inline("🧹 تنظيف الإدمن", b"clean_menu")]
    ])

async def show_transfer_menu(event):
    await event.respond("قائمة النقل:", buttons=[
        [Button.inline("📝 نقل عادي (وصف)", b"new_transfer")],
        [Button.inline("📦 نقل تجميعي (بدون وصف)", b"batch_transfer")],
        [Button.inline("🗑️ إعادة ضبط", b"reset")]
    ])

# ================= RUN ENGINE =================
async def run(uid):
    s = state[uid]
    # التأكد من استخدام الجلسة الصحيحة (سواء محمية أو مؤقتة)
    client = s.get("client")
    if not client or not client.is_connected():
        client = TelegramClient(StringSession(s["raw_session"]), API_ID, API_HASH)
        await client.start()
        s["client"] = client

    delay = s.get("delay", 10)

    if s["mode"].startswith("transfer") or s["mode"] == "batch_transfer":
        src = await client.get_entity("me"); dst = await client.get_entity(s["target"])
    else:
        src = await client.get_entity(s["source"]); dst = "me"

    msgs = await client.get_messages(src, limit=0)
    total = msgs.total
    batch = []

    async for m in client.iter_messages(src, limit=None, offset_id=s.get("last_id", 0)):
        if not s["running"]: break
        if not m.video: continue

        if s["mode"] in ["batch_transfer", "steal", "steal_protected"]:
            batch.append(m.video)
            if len(batch) == 10:
                await client.send_file(dst, batch)
                s["sent"] += 10
                await s["status"].edit(f"📊 {s['mode']}: {s['sent']} / {total}")
                batch.clear()
                if delay > 0: await asyncio.sleep(delay)
            s["last_id"] = m.id
            continue 

        await client.send_file(dst, m.video, caption=clean_caption(m.text))
        s["sent"] += 1; s["last_id"] = m.id
        await s["status"].edit(f"📊 نقل عادي: {s['sent']} / {total}")
        await asyncio.sleep(delay)

    if batch:
        await client.send_file(dst, batch)
        s["sent"] += len(batch)
    
    await s["status"].edit(f"✅ اكتملت العملية: {s['sent']} مقطع")

bot.run_until_disconnected()
