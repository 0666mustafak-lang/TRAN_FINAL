import os
import asyncio
import re
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError as Telethon2FA
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

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb_handler(event):
    uid = event.sender_id; s = state.setdefault(uid, {}); d = event.data

    if d == b"main_menu": await show_main_menu(event)
    elif d == b"transfer_menu": await show_transfer_menu(event)
    elif d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل الرقم:")
    elif d == b"extract_session": s["step"] = "ex_phone"; await event.respond("🔑 أرسل الرقم:")
    
    # --- إضافة كود خروج المؤقت ---
    elif d == b"clear_temp":
        if "client" in s:
            try: await s["client"].log_out()
            except: pass
            del s["client"]
        if "raw_session" in s: del s["raw_session"]
        s["step"] = None
        await event.edit("✅ تم الخروج من الحساب المؤقت.")

    elif d == b"sessions":
        accs = await get_accounts()
        btns = [[Button.inline(n, f"load_{k}".encode())] for k, n in accs]
        btns.append([Button.inline("🔙 رجوع", b"back_start")])
        await event.edit("🛡 اختر الحساب:", buttons=btns)
    elif d == b"back_start":
        await event.edit("📟 النظام:", buttons=[[Button.inline("🛡 الحسابات", b"sessions")],[Button.inline("📲 دخول مؤقت", b"temp")],[Button.inline("🔑 استخراج", b"extract_session")],[Button.inline("🧹 خروج المؤقت", b"clear_temp")]])

    elif d.startswith(b"load_"):
        key = d.decode().replace("load_", "")
        s["raw_session"] = os.environ[key]
        s["client"] = TelegramClient(StringSession(s["raw_session"]), API_ID, API_HASH)
        await s["client"].connect(); await show_main_menu(event)

    elif d in [b"new_transfer", b"batch_transfer"]:
        s.update({"mode": "normal" if d == b"new_transfer" else "batch", "step": "delay", "sent": 0, "last_id": 0})
        await event.edit("⏱️ أرسل التأخير:", buttons=[[Button.inline("🔙 رجوع", b"transfer_menu")]])
    
    elif d in [b"resume_normal", b"resume_batch"]:
        s.update({"mode": "normal" if d == b"resume_normal" else "batch", "step": "delay"})
        await event.edit(f"⏯️ استكمال من {s.get('sent', 0)}.. أرسل التأخير:", buttons=[[Button.inline("🔙 رجوع", b"transfer_menu")]])

    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0, "last_id": 0})
        await event.edit("⚡ أرسل المصدر:", buttons=[[Button.inline("🔙 رجوع", b"main_menu")]])

    elif d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link", "sent": 0, "last_id": 0})
        await event.edit("🔓 أرسل المصدر المحمي:", buttons=[[Button.inline("🔙 رجوع", b"main_menu")]])

    elif d == b"clean_menu":
        if "raw_session" not in s: return await event.answer("❌ سجل دخول أولاً", alert=True)
        lmsg = await event.respond("🔍 جاري جلب القنوات...")
        async with PyroClient(f"p_{uid}", API_ID, API_HASH, session_string=s["raw_session"]) as pc:
            btns = []
            async for dialog in pc.get_dialogs(limit=50):
                if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]:
                    try:
                        m = await pc.get_chat_member(dialog.chat.id, "me")
                        if m.status in [enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR]:
                            btns.append([Button.inline(f"🧹 {dialog.chat.title[:20]}", f"cln_{dialog.chat.id}".encode())])
                    except: continue
            btns.append([Button.inline("🔙 رجوع", b"transfer_menu")])
            await lmsg.edit("✅ اختر الدردشة:", buttons=btns)

    elif d.startswith(b"cln_"):
        cid = int(d.decode().split("_")[1])
        asyncio.create_task(run_pyro_clean(event, cid, s["raw_session"]))

    elif d == b"stop": s["running"] = False; await event.answer("🛑 توقف")
    elif d == b"reset": s.update({"sent": 0, "last_id": 0}); await event.answer("🗑️ تم التصفير")

# ================= MENUS =================
async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل", b"transfer_menu")], [Button.inline("⚡ السرقة", b"steal"), Button.inline("🔓 السرقة المحمية", b"steal_protected")]]
    if isinstance(event, events.CallbackQuery): await event.edit("✅ خيارات الحساب:", buttons=btns)
    else: await event.respond("✅ خيارات الحساب:", buttons=btns)

async def show_transfer_menu(event):
    btns = [[Button.inline("📝 عادي", b"new_transfer"), Button.inline("⏯️ استكمال", b"resume_normal")],[Button.inline("📦 تجميعي", b"batch_transfer"), Button.inline("⏯️ استكمال", b"resume_batch")],[Button.inline("🧹 تنظيف الإدمن", b"clean_menu")],[Button.inline("🗑️ ضبط", b"reset"), Button.inline("🔙 رجوع", b"main_menu")]]
    await event.edit("📤 قائمة النقل:", buttons=btns)

# ================= ENGINES =================
async def run_engine(uid):
    s = state[uid]; client = s["client"]; mode = s["mode"]
    src = s.get("source", "me"); dst = s.get("target", "me")
    batch = []
    
    # محاولة جلب التوتال مع تفادي تعليق القنوات العملاقة
    try:
        m_info = await client.get_messages(src, limit=0)
        total = m_info.total
    except: total = "???"

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
        await s["status"].edit(f"📊 Progress: {s['sent']} / {total}")
    await s["status"].edit(f"✅ اكتمل: {s['sent']} / {total}")

async def run_pyro_clean(event, chat_id, session):
    status_msg = await event.respond("🔄 **جاري حذف رسائل الخدمة بسرعة...**")
    try:
        async with PyroClient(f"c_{event.sender_id}", API_ID, API_HASH, session_string=session) as pc:
            s_ids = [m.id async for m in pc.get_chat_history(chat_id, limit=500) if m.service]
            if s_ids:
                for i in range(0, len(s_ids), 100): await pc.delete_messages(chat_id, s_ids[i:i+100])
            
            await status_msg.edit(f"✅ حذفت {len(s_ids)} خدمة.\n👤 جاري طرد الأعضاء...")
            b_count = 0
            async for member in pc.get_chat_members(chat_id):
                if member.status not in [enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR]:
                    try:
                        await pc.ban_chat_member(chat_id, member.user.id); b_count += 1
                        if b_count % 5 == 0: await status_msg.edit(f"📊 التقدم:\n👤 طرد: {b_count}\n🗑 رسائل: {len(s_ids)}")
                        await asyncio.sleep(1.5)
                    except: continue
            await status_msg.edit(f"✅ **اكتمل التنظيف!**\n👤 مطرودين: {b_count}\n🗑 رسائل: {len(s_ids)}")
    except Exception as e: await status_msg.edit(f"❌ خطأ: {e}")

bot.run_until_disconnected()
