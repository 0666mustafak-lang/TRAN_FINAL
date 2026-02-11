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
        await event.respond("📟 **مرحباً بك في النظام الشامل**\n\nاختر وسيلة الدخول:", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج سيشن", b"extract_session")],
            [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
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
        return

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

    if step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"; await event.respond("🔗 أرسل الهدف")
        return

    if step == "target":
        s["target"] = text; s["running"] = True
        s["status"] = await event.respond("🚀 بدء العملية...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid)); return

    if step == "steal_link":
        s["source"] = text; s["target"] = "me"; s["running"] = True
        s["status"] = await event.respond("⚡ بدء السرقة...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid)); return

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb(event):
    uid = event.sender_id
    s = state.setdefault(uid, {})
    d = event.data

    if d == b"sessions":
        accs = await get_accounts()
        if not accs: await event.answer("❌ لا توجد حسابات", alert=True); return
        btns = [[Button.inline(n, f"load_{k}".encode())] for k, n in accs]
        await event.edit("🛡 الحسابات المحمية:", buttons=btns)
        return

    if d.startswith(b"load_"):
        sess_key = d.decode().replace("load_", "")
        s["raw_session"] = os.environ[sess_key]
        s["client"] = TelegramClient(StringSession(s["raw_session"]), API_ID, API_HASH)
        await s["client"].connect()
        await show_main_menu(event)
        return

    if d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل رقم الهاتف"); return
    
    if d == b"extract_session":
        if "raw_session" not in s: await event.answer("❌ سجل دخول أولاً", alert=True); return
        await event.respond(f"🔑 **كود السيشن الخاص بك:**\n\n`{s['raw_session']}`")

    if d == b"clear_temp":
        if uid in TEMP_SESSIONS:
            try: await TEMP_SESSIONS[uid].log_out()
            except: pass
            del TEMP_SESSIONS[uid]
        s.clear()
        await event.respond("🧹 تم تسجيل الخروج.")

    if d == b"transfer_menu": await show_transfer_menu(event); return
    
    if d in [b"new_transfer", b"batch_transfer"]:
        s.update({"mode": "normal" if d == b"new_transfer" else "batch", "step": "delay", "sent": 0, "last_id": 0})
        await event.respond("⏱️ أرسل التأخير بالثواني:")
        return

    if d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0, "delay": 0, "last_id": 0})
        await event.respond("🔗 أرسل رابط القناة المصدر:")
        return

    if d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link", "sent": 0, "delay": 0, "last_id": 0})
        await event.respond("🔓 أرسل رابط القناة المحمية:")
        return

    if d == b"reset":
        s.update({"last_id": 0, "sent": 0})
        await event.answer("🗑️ تم إعادة ضبط العدادات", alert=True)
        return

    if d == b"clean_menu":
        if not s.get("raw_session"): await event.respond("❌ سجل دخول أولاً"); return
        lmsg = await event.respond("🔍 جاري فحص القنوات...")
        async with PyroClient(f"p_{uid}", API_ID, API_HASH, session_string=s["raw_session"]) as pc:
            btns = []
            async for dialog in pc.get_dialogs():
                if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]:
                    try:
                        member = await pc.get_chat_member(dialog.chat.id, "me")
                        if member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                            btns.append([Button.inline(f"🧹 {dialog.chat.title[:20]}", f"pclean_{dialog.chat.id}".encode())])
                    except: continue
            if btns: await lmsg.edit("✅ اختر قناة لتنظيفها:", buttons=btns)
            else: await lmsg.edit("❌ لا توجد قنوات مشرف فيها.")

    if d.startswith(b"pclean_"):
        chat_id = int(d.decode().split("_")[1])
        asyncio.create_task(run_cleaning(event, chat_id, s["raw_session"]))

    if d == b"stop": s["running"] = False; await event.answer("🛑 تم الإيقاف")

# ================= MENUS =================
async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل", b"transfer_menu")],
            [Button.inline("⚡ السرقة", b"steal")],
            [Button.inline("🔓 السرقة المحمية", b"steal_protected")],
            [Button.inline("🧹 تنظيف الإدمن", b"clean_menu")]]
    if isinstance(event, events.CallbackQuery): await event.edit("✅ القائمة الرئيسية:", buttons=btns)
    else: await event.respond("✅ القائمة الرئيسية:", buttons=btns)

async def show_transfer_menu(event):
    await event.edit("📤 قائمة النقل:", buttons=[
        [Button.inline("📝 نقل عادي (وصف)", b"new_transfer")],
        [Button.inline("📦 نقل تجميعي (10/10)", b"batch_transfer")],
        [Button.inline("🗑️ إعادة ضبط", b"reset")]
    ])

# ================= ENGINES =================
async def run_engine(uid):
    s = state[uid]; client = s["client"]
    mode, delay = s["mode"], s["delay"]
    src = s.get("source", "me"); dst = s.get("target", "me")
    sent_count, batch = 0, []

    async for m in client.iter_messages(src, offset_id=s.get("last_id", 0)):
        if not s.get("running"): break
        if not m.video: continue

        if mode in ["batch", "steal", "steal_protected"]:
            batch.append(m)
            if len(batch) == 10:
                for vid in batch: await client.send_file(dst, vid)
                sent_count += 10; s["last_id"] = m.id; batch.clear()
                await s["status"].edit(f"📊 التقدم ({mode}): {sent_count}")
                if delay > 0 and mode == "batch": await asyncio.sleep(delay)
        else:
            await client.send_file(dst, m, caption=clean_caption(m.text))
            sent_count += 1; s["last_id"] = m.id
            await s["status"].edit(f"📊 التقدم: {sent_count}")
            if delay > 0: await asyncio.sleep(delay)

    if batch and s.get("running"):
        for vid in batch: await client.send_file(dst, vid)
        sent_count += len(batch)
    await s["status"].edit(f"✅ اكتملت العملية: {sent_count} مقطع")

async def run_cleaning(event, chat_id, sess):
    status = await event.respond("🔄 **جاري حذف رسائل الخدمة...**")
    async with PyroClient(f"c_{event.sender_id}", API_ID, API_HASH, session_string=sess) as pc:
        s_count = 0; service_msg_ids = []
        async for message in pc.get_chat_history(chat_id, limit=500):
            if message.service:
                service_msg_ids.append(message.id); s_count += 1
        
        if service_msg_ids:
            for i in range(0, len(service_msg_ids), 100):
                await pc.delete_messages(chat_id, service_msg_ids[i:i+100])
                await asyncio.sleep(0.5)

        await status.edit(f"✅ تم حذف `{s_count}` رسالة خدمة.\n👤 جاري طرد الأعضاء (كل 2 ثانية)...")
        b_count = 0
        async for member in pc.get_chat_members(chat_id):
            if member.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                try:
                    await pc.ban_chat_member(chat_id, member.user.id); b_count += 1
                    if b_count % 5 == 0: await status.edit(f"📊 طرد: `{b_count}` | حذف: `{s_count}`")
                    await asyncio.sleep(2)
                except: continue
        await status.edit(f"✅ **اكتمل التنظيف!**\n👤 المطرودين: `{b_count}` | الرسائل: `{s_count}`")

bot.run_until_disconnected()
