import asyncio
import os
import re
import json
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError

# استيراد Pyrogram لميزة التنظيف
from pyrogram import Client as PyroClient, enums
from pyrogram.errors import SessionPasswordNeeded as Pyro2FA

# ================= CONFIG =================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"
CHANNELS_FILE = "saved_channels.json"

# ================= AUTH & STORAGE =================
def load_authorized():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE) as f:
            try: return set(map(int, f.read().splitlines()))
            except: return set()
    return set()

def save_authorized(uid):
    with open(AUTH_FILE, "a") as f: f.write(f"{uid}\n")

AUTHORIZED_USERS = load_authorized()

def load_channels():
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE) as f:
            try: return json.load(f)
            except: pass
    return []

def save_channels():
    with open(CHANNELS_FILE, "w") as f: json.dump(RECENT_CHANNELS, f, indent=2)

RECENT_CHANNELS = load_channels()
MAX_RECENT = 7

# ================= BOT START =================
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
                c = TelegramClient(StringSession(os.environ[k]), API_ID, API_HASH)
                await c.connect()
                me = await c.get_me()
                accs.append((k, me.first_name or me.username or "NoName"))
                await c.disconnect()
            except: pass
    return accs

# ================= MESSAGE ROUTER =================
@bot.on(events.NewMessage)
async def router(event):
    uid = event.sender_id
    text = (event.text or "").strip()
    s = state.setdefault(uid, {})

    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            AUTHORIZED_USERS.add(uid); save_authorized(uid)
            await event.respond("✅ تم الدخول، أرسل /start")
        else: await event.respond("🔐 أرسل رمز الدخول")
        return

    if text == "/start":
        s.clear()
        await event.respond(
            "اختر طريقة الدخول:",
            buttons=[
                [Button.inline("🛡 الحسابات المحمية", b"sessions")],
                [Button.inline("📲 دخول مؤقت", b"temp")],
                [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
            ]
        )
        return

    step = s.get("step")

    # دخول مؤقت + استخراج سيشن
    if step == "temp_phone":
        if uid in TEMP_SESSIONS:
            try: await TEMP_SESSIONS[uid].disconnect()
            except: pass
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
            if s.get("extract_mode"):
                await event.respond(f"✅ تم استخراج السيشن بنجاح:\n\n`{s['raw_session']}`")
                s["extract_mode"] = False
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"
            await event.respond("🔐 أرسل رمز 2FA")
            return
        except Exception as e: await event.respond(f"❌ خطأ: {e}"); return
        s["step"] = "main"
        await show_main_menu_msg(uid)
        return

    if step == "temp_2fa":
        try:
            await s["client"].sign_in(password=text)
            s["raw_session"] = s["client"].session.save()
            if s.get("extract_mode"):
                await event.respond(f"✅ تم استخراج السيشن بنجاح:\n\n`{s['raw_session']}`")
                s["extract_mode"] = False
            s["step"] = "main"; await show_main_menu_msg(uid)
        except Exception as e: await event.respond(f"❌ خطأ في الباسورد: {e}")
        return

    # مدخلات النقل والسرقة
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
        s["status"] = await event.respond("⚡ بدء السرقة السريعة...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
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
        if not accs: await event.respond("❌ لا توجد حسابات محمية"); return
        await event.respond("🛡 الحسابات:", buttons=[[Button.inline(n, k.encode())] for k, n in accs])
        s["step"] = "choose_session"; return

    if s.get("step") == "choose_session":
        session_str = os.environ.get(d.decode())
        s["client"] = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await s["client"].start()
        s["raw_session"] = session_str
        s["step"] = "main"; await show_main_menu_msg(uid); return

    if d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل رقم الهاتف"); return

    if d == b"clear_temp":
        for c in TEMP_SESSIONS.values():
            try: await c.log_out()
            except: pass
        TEMP_SESSIONS.clear(); await event.respond("🧹 تم تسجيل الخروج"); return

    if d == b"transfer_menu": await show_transfer_menu(event); return
    if d == b"new_transfer":
        s.update({"mode": "transfer", "step": "delay", "last_id": 0, "sent": 0})
        await event.respond("⏱️ أرسل التأخير"); return
    if d == b"batch_transfer":
        s.update({"mode": "batch_transfer", "step": "delay", "last_id": 0, "sent": 0})
        await event.respond("⏱️ أرسل التأخير"); return
    
    if d == b"resume":
        if not RECENT_CHANNELS: await event.respond("❌ لا توجد عمليات سابقة"); return
        buttons = [[Button.inline(f"{c['title']} ({c['sent']})", f"res_{i}".encode())] for i, c in enumerate(RECENT_CHANNELS)]
        await event.respond("اختر للاستكمال:", buttons=buttons); return

    if d.startswith(b"res_"):
        idx = int(d.decode().split("_")[1]); s.update(RECENT_CHANNELS[idx])
        s["running"] = True; s["status"] = await event.respond("▶️ استكمال...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run(uid)); return

    if d == b"reset": RECENT_CHANNELS.clear(); save_channels(); await event.respond("🗑️ تم المسح"); return
    
    if d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "last_id": 0, "sent": 0})
        await event.respond("🔗 أرسل رابط القناة"); return
    if d == b"steal_protected":
        s.update({"mode": "steal_protected", "step": "steal_link", "last_id": 0, "sent": 0})
        await event.respond("🔗 أرسل رابط القناة (المحمية)"); return

    if d == b"clean_menu": asyncio.create_task(pyro_clean_logic(uid)); return
    if d.startswith(b"pclean_"):
        chat_id = int(d.decode().split("_")[1]); asyncio.create_task(start_cleaning_process(uid, chat_id)); return

    if d == b"extract_session":
        if s.get("raw_session"): await event.respond(f"✅ السيشن الحالي:\n\n`{s['raw_session']}`")
        else: s["extract_mode"] = True; s["step"] = "temp_phone"; await event.respond("📲 أرسل رقم الهاتف للاستخراج:"); return

    if d == b"stop": s["running"] = False

# ================= MENUS =================
async def show_main_menu_msg(uid):
    await bot.send_message(uid, "اختر العملية:", buttons=[
        [Button.inline("📤 النقل", b"transfer_menu"), Button.inline("⚡ السرقة", b"steal")],
        [Button.inline("🔓 السرقة المحمية", b"steal_protected"), Button.inline("🧹 تنظيف الإدمن", b"clean_menu")],
        [Button.inline("🔑 استخراج سيشن", b"extract_session")]
    ])

async def show_transfer_menu(event):
    await event.respond("قائمة النقل:", buttons=[
        [Button.inline("📤 نقل جديد", b"new_transfer")],
        [Button.inline("📦 نقل تجميعي", b"batch_transfer")],
        [Button.inline("▶️ استكمال", b"resume")],
        [Button.inline("🗑️ إعادة ضبط", b"reset")]
    ])

# ================= PYROGRAM CLEAN LOGIC =================
async def pyro_clean_logic(uid):
    s = state[uid]
    if not s.get("raw_session"): await bot.send_message(uid, "❌ سجل دخول أولاً"); return
    load_msg = await bot.send_message(uid, "🔍 جاري فحص الإدمن...")
    try:
        async with PyroClient(f"pyro_{uid}", API_ID, API_HASH, session_string=s["raw_session"]) as pc:
            btns = []
            async for d in pc.get_dialogs(limit=50):
                if d.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP, enums.ChatType.CHANNEL]:
                    try:
                        m = await pc.get_chat_member(d.chat.id, "me")
                        if m.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                            btns.append([Button.inline(f"🧹 {d.chat.title}", f"pclean_{d.chat.id}".encode())])
                    except: continue
            if btns: await load_msg.edit("✅ اختر القناة للتنظيف:", buttons=btns)
            else: await load_msg.edit("❌ لست مشرفاً في أي قناة.")
    except Exception as e: await load_msg.edit(f"❌ خطأ: {e}")

async def start_cleaning_process(uid, chat_id):
    s = state[uid]; status = await bot.send_message(uid, "🚀 بدأ التنظيف...")
    try:
        async with PyroClient(f"p_ex_{uid}", API_ID, API_HASH, session_string=s["raw_session"]) as pc:
            await status.edit("🔄 حذف رسائل الخدمة...")
            s_ids = [m.id async for m in pc.get_chat_history(chat_id, limit=500) if m.service]
            if s_ids:
                for i in range(0, len(s_ids), 100): await pc.delete_messages(chat_id, s_ids[i:i+100]); await asyncio.sleep(0.5)
            await status.edit(f"✅ حذفت {len(s_ids)} رسالة.\n👤 جاري طرد الأعضاء...")
            b_count = 0
            async for m in pc.get_chat_members(chat_id):
                if m.status not in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
                    try:
                        await pc.ban_chat_member(chat_id, m.user.id); b_count += 1
                        if b_count % 5 == 0: await status.edit(f"📊 طردت: {b_count}")
                        await asyncio.sleep(2)
                    except: continue
            await status.edit(f"✅ اكتمل التنظيف!\n👤 المطرودين: {b_count}\n📍 الحساب ما زال متصلاً.")
    except Exception as e: await status.edit(f"❌ خطأ: {e}")

# ================= RUN (TRANSFER & STEAL) =================
async def run(uid):
    s = state[uid]; c = s["client"]
    try:
        if s["mode"].startswith("steal"):
            src = await c.get_entity(s["source"]); dst = "me"
        else:
            src = await c.get_entity("me"); dst = await c.get_entity(s["target"])

        batch = []
        async for m in c.iter_messages(src, offset_id=s.get("last_id", 0), reverse=True):
            if not s.get("running"): break
            if not m.video: continue

            # --- سرعة السرقة القديمة ---
            if s["mode"].startswith("steal"):
                if s["mode"] == "steal_protected":
                    file = await c.download_media(m.video, file=bytes); batch.append(file)
                else: batch.append(m.video)
                if len(batch) == 10:
                    await c.send_file(dst, batch); s["sent"] += 10
                    await s["status"].edit(f"⚡ تم سرقة: {s['sent']}")
                    batch.clear()
                s["last_id"] = m.id
                continue # تخطي الـ sleep للسرعة

            # --- نظام النقل (تجميعي أو عادي) ---
            if s["mode"] == "batch_transfer":
                batch.append(m.video)
                if len(batch) == 10:
                    await c.send_file(dst, batch); s["sent"] += 10
                    await s["status"].edit(f"📦 نقل تجميعي: {s['sent']}")
                    batch.clear(); await asyncio.sleep(5)
                s["last_id"] = m.id
            else:
                await c.send_file(dst, m.video, caption=clean_caption(m.text))
                s["last_id"] = m.id; s["sent"] += 1
                await s["status"].edit(f"📊 نقل: {s['sent']}")

            # تحديث الذاكرة
            t_id = str(dst.id) if hasattr(dst, 'id') else s.get("target")
            RECENT_CHANNELS[:] = [x for x in RECENT_CHANNELS if x.get("target") != t_id]
            RECENT_CHANNELS.insert(0, {"title": getattr(dst,'title','Target'), "target": t_id, "last_id": s["last_id"], "sent": s["sent"], "mode": s["mode"], "delay": s.get("delay", 10)})
            del RECENT_CHANNELS[MAX_RECENT:]; save_channels()
            await asyncio.sleep(s.get("delay", 10))

        if batch: await c.send_file(dst, batch); s["sent"] += len(batch)
        await s["status"].edit(f"✅ اكتملت العملية بنجاح! ({s['sent']})")
    except Exception as e: await bot.send_message(uid, f"❌ خطأ: {e}")

bot.run_until_disconnected()
