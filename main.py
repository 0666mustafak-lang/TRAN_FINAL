import os
import asyncio
import re
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError as Telethon2FA
from pyrogram import Client as PyroClient, enums, filters
from pyrogram.errors import SessionPasswordNeeded as Pyro2FA

# --- إعدادات البيئة ---
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

# --- إعداد البوت الأساسي (Telethon) ---
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}

# دالة تنظيف الكابشن
def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

# --- القوائم الرئيسية ---
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
        [Button.inline("🧹 تنظيف الإدمن", b"clean_menu")],
        [Button.inline("🗑️ ضبط", b"reset"), Button.inline("🔙 رجوع", b"main_menu")]
    ]
    await event.edit("📤 قائمة النقل والتنظيف:", buttons=btns)

# --- معالج الرسائل (Telethon) ---
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    state[event.sender_id] = {}
    await event.respond("📟 **مرحباً بك في النظام المتكامل**", buttons=[
        [Button.inline("🛡 الحسابات المحمية", b"sessions")],
        [Button.inline("📲 دخول مؤقت", b"temp")],
        [Button.inline("🔑 استخراج سيشن (جديد)", b"extract_session")],
        [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
    ])

@bot.on(events.NewMessage)
async def handle_text(event):
    uid = event.sender_id
    if uid not in state or event.text.startswith("/"): return
    s = state[uid]
    step = s.get("step")

    # منطق تسجيل الدخول (Telethon) للنقل والسرقة
    if step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        s["client"] = c; await c.connect()
        try:
            sent = await c.send_code_request(event.text)
            s.update({"phone": event.text, "hash": sent.phone_code_hash, "step": "temp_code"})
            await event.respond("🔐 أرسل كود التحقق:")
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
    
    elif step == "temp_code":
        try:
            await s["client"].sign_in(s["phone"], event.text, phone_code_hash=s["hash"])
            s["raw_session"] = s["client"].session.save()
            await show_main_menu(event)
        except Telethon2FA:
            s["step"] = "temp_2fa"; await event.respond("🔐 أرسل رمز التحقق بخطوتين:")
        except Exception as e: await event.respond(f"❌ خطأ: {e}")

    # منطق استخراج سيشن (جديد)
    elif step == "ex_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        s["ex_c"] = c; await c.connect()
        sent = await c.send_code_request(event.text)
        s.update({"ex_p": event.text, "ex_h": sent.phone_code_hash, "step": "ex_code"})
        await event.respond("🔑 أرسل كود الاستخراج:")
    
    elif step == "ex_code":
        await s["ex_c"].sign_in(s["ex_p"], event.text, phone_code_hash=s["ex_h"])
        await event.respond(f"✅ السيشن المستخرج:\n\n`{s['ex_c'].session.save()}`")

    # إدخال روابط السرقة والنقل
    elif step == "delay":
        s["delay"] = int(event.text) if event.text.isdigit() else 10
        s["step"] = "target"; await event.respond("🔗 أرسل معرف القناة الهدف:", buttons=[[Button.inline("🔙 رجوع", b"transfer_menu")]])
    
    elif step == "target":
        s.update({"target": event.text, "running": True})
        s["status"] = await event.respond("🚀 جاري البدء...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))

    elif step == "steal_link":
        s.update({"source": event.text, "target": "me", "running": True})
        s["status"] = await event.respond("⚡ جاري السرقة...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))

# --- معالج الكولباك (Callbacks) ---
@bot.on(events.CallbackQuery)
async def cb_handler(event):
    uid = event.sender_id
    s = state.setdefault(uid, {})
    d = event.data

    if d == b"main_menu": await show_main_menu(event)
    elif d == b"transfer_menu": await show_transfer_menu(event)
    elif d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل رقم الهاتف:")
    elif d == b"extract_session": s["step"] = "ex_phone"; await event.respond("🔑 أرسل الرقم لاستخراج السيشن:")
    
    elif d in [b"new_transfer", b"batch_transfer"]:
        s.update({"mode": "normal" if d == b"new_transfer" else "batch", "step": "delay", "sent": 0, "last_id": 0})
        await event.edit("⏱️ أرسل وقت التأخير:", buttons=[[Button.inline("🔙 رجوع", b"transfer_menu")]])
    
    elif d in [b"resume_normal", b"resume_batch"]:
        s.update({"mode": "normal" if d == b"resume_normal" else "batch", "step": "delay"})
        await event.edit(f"⏯️ استكمال من {s.get('sent', 0)}.. أرسل التأخير:", buttons=[[Button.inline("🔙 رجوع", b"transfer_menu")]])

    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0, "last_id": 0})
        await event.edit("⚡ أرسل رابط المصدر للسرقة:", buttons=[[Button.inline("🔙 رجوع", b"main_menu")]])

    elif d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link", "sent": 0, "last_id": 0})
        await event.edit("🔓 أرسل رابط المصدر (المحمي):", buttons=[[Button.inline("🔙 رجوع", b"main_menu")]])

    elif d == b"clean_menu":
        if "raw_session" not in s: return await event.answer("❌ سجل دخول أولاً!", alert=True)
        # تشغيل Pyrogram لجلب القنوات
        await event.answer("🔍 جاري الفحص...")
        async with PyroClient(f"pyro_{uid}", API_ID, API_HASH, session_string=s["raw_session"]) as pc:
            btns = []
            async for dialog in pc.get_dialogs(limit=50):
                if dialog.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]:
                    try:
                        m = await pc.get_chat_member(dialog.chat.id, "me")
                        if m.status in [enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR]:
                            btns.append([Button.inline(f"🧹 {dialog.chat.title[:20]}", f"clean_{dialog.chat.id}".encode())])
                    except: continue
            btns.append([Button.inline("🔙 رجوع", b"transfer_menu")])
            await event.edit("✅ اختر الدردشة لتنظيفها:", buttons=btns)

    elif d.startswith(b"clean_"):
        chat_id = int(d.decode().split("_")[1])
        asyncio.create_task(run_pyro_clean(event, chat_id, s["raw_session"]))

    elif d == b"stop": s["running"] = False; await event.answer("🛑 تم الإيقاف")
    elif d == b"reset": s.update({"sent": 0, "last_id": 0}); await event.answer("🗑️ تم التصفير")

# --- محرك التنظيف (Pyrogram) ---
async def run_pyro_clean(event, chat_id, session):
    msg = await event.respond("🔄 **جاري بدء التنظيف (بايروغرام)...**")
    async with PyroClient(f"cleaner_{event.sender_id}", API_ID, API_HASH, session_string=session) as pc:
        # 1. حذف رسائل الخدمة
        s_count = 0
        service_ids = [m.id async for m in pc.get_chat_history(chat_id, limit=300) if m.service]
        if service_ids:
            await pc.delete_messages(chat_id, service_ids)
            s_count = len(service_ids)
        
        await msg.edit(f"🗑 تم حذف {s_count} رسالة خدمة..\n👤 جاري طرد الأعضاء...")
        
        # 2. طرد الأعضاء
        b_count = 0
        async for member in pc.get_chat_members(chat_id):
            if member.status not in [enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR]:
                try:
                    await pc.ban_chat_member(chat_id, member.user.id)
                    b_count += 1
                    if b_count % 10 == 0: await msg.edit(f"📊 طرد: {b_count} | خدمة: {s_count}")
                    await asyncio.sleep(1) # آمن
                except: continue
        await msg.edit(f"✅ **اكتمل التنظيف!**\n\n👤 المطرودين: {b_count}\n🗑 رسائل الخدمة: {s_count}")

# --- محرك النقل (Telethon) ---
async def run_engine(uid):
    s = state[uid]; client = s["client"]; mode = s["mode"]
    src = s.get("source", "me"); dst = s.get("target", "me")
    batch = []
    
    async for m in client.iter_messages(src, offset_id=s.get("last_id", 0), reverse=True):
        if not s.get("running"): break
        if not m.video: continue

        if mode in ["batch", "steal", "steal_protected"]:
            batch.append(m)
            if len(batch) == 10:
                await client.send_file(dst, batch)
                s["sent"] += 10; s["last_id"] = m.id; batch.clear()
                await s["status"].edit(f"📊 {mode}: {s['sent']}")
                if mode == "batch": await asyncio.sleep(s["delay"])
        else:
            await client.send_file(dst, m, caption=clean_caption(m.text))
            s["sent"] += 1; s["last_id"] = m.id
            await s["status"].edit(f"📊 عادي: {s['sent']}")
            await asyncio.sleep(s["delay"])
            
    if batch and s.get("running"): await client.send_file(dst, batch)
    await s.get("status").edit("✅ اكتملت العملية!")

print("✅ النظام يعمل الآن...")
bot.run_until_disconnected()
