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
        await event.respond("📟 **مرحباً بك في النظام المتكامل**", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج سيشن (حساب جديد)", b"extract_new_session")],
            [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
        ])
        return

    step = s.get("step")
    
    # استخراج سيشن جديد
    if step in ["ex_phone", "ex_code", "ex_2fa"]:
        if step == "ex_phone":
            c = TelegramClient(StringSession(), API_ID, API_HASH)
            s["ex_client"] = c; await c.connect()
            try:
                sent = await c.send_code_request(text)
                s.update({"ex_phone": text, "ex_hash": sent.phone_code_hash, "step": "ex_code"})
                await event.respond("🔑 أرسل كود التحقق للاستخراج:")
            except Exception as e: await event.respond(f"❌ خطأ: {e}")
        elif step == "ex_code":
            try:
                await s["ex_client"].sign_in(s["ex_phone"], text, phone_code_hash=s["ex_hash"])
                raw = s["ex_client"].session.save()
                await event.respond(f"✅ **السيشن الجديد:**\n\n`{raw}`")
                await s["ex_client"].disconnect(); del s["step"]
            except SessionPasswordNeededError:
                s["step"] = "ex_2fa"; await event.respond("🔐 أرسل رمز 2FA:")
            except Exception as e: await event.respond(f"❌ خطأ: {e}")
        elif step == "ex_2fa":
            try:
                await s["ex_client"].sign_in(password=text)
                raw = s["ex_client"].session.save()
                await event.respond(f"✅ **السيشن الجديد:**\n\n`{raw}`")
                await s["ex_client"].disconnect(); del s["step"]
            except Exception as e: await event.respond(f"❌ خطأ: {e}")
        return

    # الدخول المؤقت للنقل
    if step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        s["client"] = c; await c.connect()
        try:
            sent = await c.send_code_request(text)
            s.update({"phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
            await event.respond("🔑 أرسل كود التحقق:")
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
    elif step == "temp_code":
        try:
            await s["client"].sign_in(s["phone"], text, phone_code_hash=s["hash"])
            s["raw_session"] = s["client"].session.save()
            s["step"] = "main"; await show_main_menu(event)
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"; await event.respond("🔐 أرسل رمز 2FA:")
    elif step == "temp_2fa":
        try:
            await s["client"].sign_in(password=text)
            s["raw_session"] = s["client"].session.save()
            s["step"] = "main"; await show_main_menu(event)
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
    elif step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"; await event.respond("🔗 أرسل الهدف (المعرف):")
    elif step == "target":
        s["target"] = text; s["running"] = True
        s["status"] = await event.respond("🚀 جاري البدء...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))
    elif step == "steal_link":
        s["source"] = text; s["target"] = "me"; s["running"] = True
        s["status"] = await event.respond("⚡ جاري السرقة...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
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
    elif d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل الرقم:")
    elif d == b"extract_new_session": s["step"] = "ex_phone"; await event.respond("📲 أرسل الرقم للاستخراج:")
    elif d == b"clear_temp":
        if "client" in s: await s["client"].log_out()
        s.clear(); await event.respond("🧹 تم مسح الجلسة.")
    elif d == b"transfer_menu": await show_transfer_menu(event)
    elif d in [b"new_transfer", b"batch_transfer"]:
        s.update({"mode": "normal" if d == b"new_transfer" else "batch", "step": "delay", "sent": 0, "last_id": 0})
        await event.respond("⏱️ أرسل التأخير:")
    elif d in [b"resume_normal", b"resume_batch"]:
        s.update({"mode": "normal" if d == b"resume_normal" else "batch", "step": "delay"})
        await event.respond(f"⏯️ استكمال من {s.get('sent', 0)}\nأرسل التأخير:")
    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0, "delay": 0, "last_id": 0})
        await event.respond("🔗 أرسل رابط المصدر:")
    elif d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link", "sent": 0, "delay": 0, "last_id": 0})
        await event.respond("🔓 أرسل المصدر المحمي:")
    elif d == b"clean_menu":
        if "raw_session" not in s: await event.answer("❌ سجل دخول أولاً", alert=True); return
        lmsg = await event.respond("🔍 جاري جلب القنوات للتنظيف...")
        async with PyroClient(f"p_{uid}", API_ID, API_HASH, session_string=s["raw_session"]) as pc:
            btns = []
            async for dialog in pc.get_dialogs():
                if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]:
                    try:
                        m = await pc.get_chat_member(dialog.chat.id, "me")
                        if m.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                            btns.append([Button.inline(f"🧹 {dialog.chat.title[:20]}", f"pclean_{dialog.chat.id}".encode())])
                    except: continue
            await lmsg.edit("🧹 اختر القناة لتنظيفها:", buttons=btns)
    elif d.startswith(b"pclean_"):
        chat_id = int(d.decode().split("_")[1])
        asyncio.create_task(run_cleaning_pyro(event, chat_id, s["raw_session"]))
    elif d == b"stop": s["running"] = False
    elif d == b"reset": s.update({"last_id": 0, "sent": 0}); await event.answer("🗑️ تم التصفير")

# ================= MENUS =================
async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل", b"transfer_menu")], 
            [Button.inline("⚡ السرقة", b"steal"), Button.inline("🔓 السرقة المحمية", b"steal_protected")]]
    await event.respond("✅ القائمة الرئيسية:", buttons=btns) if not isinstance(event, events.CallbackQuery) else await event.edit("✅ القائمة الرئيسية:", buttons=btns)

async def show_transfer_menu(event):
    await event.edit("📤 خيارات النقل والاستكمال:", buttons=[
        [Button.inline("📝 عادي (جديد)", b"new_transfer"), Button.inline("⏯️ استكمال", b"resume_normal")],
        [Button.inline("📦 تجميعي (جديد)", b"batch_transfer"), Button.inline("⏯️ استكمال", b"resume_batch")],
        [Button.inline("🧹 تنظيف الإدمن", b"clean_menu")],
        [Button.inline("🗑️ إعادة ضبط", b"reset")]
    ])

# ================= ENGINES =================
async def run_engine(uid):
    s = state[uid]; client = s["client"]; mode = s["mode"]; delay = s["delay"]
    src = s.get("source", "me"); dst = s.get("target", "me")
    
    m_info = await client.get_messages(src, limit=0)
    total = m_info.total
    batch = []

    async for m in client.iter_messages(src, offset_id=s.get("last_id", 0), reverse=True, limit=None):
        if not s.get("running"): break
        if not m.video: continue

        if mode in ["batch", "steal", "steal_protected"]:
            batch.append(m)
            if len(batch) == 10:
                await client.send_file(dst, batch)
                s["sent"] += 10; s["last_id"] = m.id; batch.clear()
                await s["status"].edit(f"📊 {mode}: {s['sent']} / {total}")
                if delay > 0 and mode == "batch": await asyncio.sleep(delay)
        else:
            await client.send_file(dst, m, caption=clean_caption(m.text))
            s["sent"] += 1; s["last_id"] = m.id
            await s["status"].edit(f"📊 عادي: {s['sent']} / {total}")
            if delay > 0: await asyncio.sleep(delay)

    if batch and s.get("running"): await client.send_file(dst, batch); s["sent"] += len(batch)
    await s["status"].edit(f"✅ اكتملت العملية: {s['sent']} / {total}")

async def run_cleaning_pyro(event, chat_id, sess_string):
    status = await event.respond("🔄 جاري التنظيف عبر بايروغرام...")
    async with PyroClient(f"c_{event.sender_id}", API_ID, API_HASH, session_string=sess_string) as pc:
        s_count = 0; s_ids = []
        async for m in pc.get_chat_history(chat_id, limit=500):
            if m.service: s_ids.append(m.id); s_count += 1
        if s_ids:
            for i in range(0, len(s_ids), 100): await pc.delete_messages(chat_id, s_ids[i:i+100])
        
        b_count = 0
        async for member in pc.get_chat_members(chat_id):
            if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                try:
                    await pc.ban_chat_member(chat_id, member.user.id); b_count += 1
                    if b_count % 5 == 0: await status.edit(f"📊 طرد: {b_count} | خدمة: {s_count}")
                    await asyncio.sleep(1)
                except: continue
        await status.edit(f"✅ انتهى التنظيف.\nطرد: {b_count}\nحذف خدمة: {s_count}")

bot.run_until_disconnected()
