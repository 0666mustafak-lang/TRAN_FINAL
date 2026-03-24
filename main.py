import os
import asyncio
import re
import random
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
    session_keys = sorted([k for k in os.environ.keys() if k.startswith("TG_SESSION_")])
    for k in session_keys:
        try:
            temp_client = TelegramClient(StringSession(os.environ[k]), API_ID, API_HASH)
            await temp_client.connect()
            if await temp_client.is_user_authorized():
                me = await temp_client.get_me()
                name = me.first_name if me.first_name else k.replace("TG_SESSION_", "")
                accs.append((k, name))
            await temp_client.disconnect()
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
            await event.respond("✅ تم التفعيل، أرسل /start")
        else: await event.respond("🔐 أرسل رمز الدخول:")
        return

    if text == "/start":
        await event.respond("📟 **نظام التحكم الاحترافي**", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج سيشن", b"extract_session")],
            [Button.inline("🧹 خروج المؤقت", b"clear_temp")]
        ])
        return

    step = s.get("step")
    # ... (نفس خطوات الدخول السابقة دون تغيير) ...
    if step == "ex_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH); s["ex_c"] = c; await c.connect()
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
        c = TelegramClient(StringSession(), API_ID, API_HASH); s["client"] = c; await c.connect()
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

    elif step == "target":
        s.update({"target": text, "running": True})
        s["status"] = await event.respond("🚀 جاري فحص الرسائل والبدء...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))
    elif step == "steal_link":
        s.update({"source": text, "target": "me", "running": True})
        s["status"] = await event.respond("⚡ جاري السرقة القصوى...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run_engine(uid))

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb_handler(event):
    uid = event.sender_id; s = state.setdefault(uid, {}); d = event.data
    if d == b"main_menu": await show_main_menu(event)
    elif d == b"transfer_menu": await show_transfer_menu(event)
    elif d == b"temp": s["step"] = "temp_phone"; await event.respond("📲 أرسل الرقم:")
    elif d == b"sessions":
        wait_msg = await event.edit("🔍 جاري جلب الحسابات...")
        accs = await get_accounts()
        if not accs: await wait_msg.edit("❌ لا توجد حسابات.", buttons=[[Button.inline("🔙 رجوع", b"back_start")]]); return
        btns = [[Button.inline(f"👤 {n}", f"load_{k}".encode())] for k, n in accs]
        btns.append([Button.inline("🔙 رجوع", b"back_start")]); await wait_msg.edit("🛡 اختر الحساب:", buttons=btns)
    elif d.startswith(b"load_"):
        key = d.decode().replace("load_", ""); s["raw_session"] = os.environ[key]
        s["client"] = TelegramClient(StringSession(s["raw_session"]), API_ID, API_HASH)
        await s["client"].connect(); await show_main_menu(event)
    
    # خيار اختيار نوع التأخير
    elif d in [b"new_transfer", b"batch_transfer"]:
        s.update({"mode": "normal" if d == b"new_transfer" else "batch", "sent": 0})
        await event.edit("⏱️ اختر نوع التأخير للنقل:", buttons=[
            [Button.inline("⏱️ ثابت (10 ثواني)", b"set_delay_10")],
            [Button.inline("🎲 متغير (10-19 ثانية)", b"set_delay_rnd")],
            [Button.inline("🔙 رجوع", b"transfer_menu")]
        ])
    
    elif d == b"set_delay_10":
        s["delay_type"] = "fixed"; s["step"] = "target"
        await event.edit("🔗 أرسل المعرف الهدف (أو me للمحفوظات):")
        
    elif d == b"set_delay_rnd":
        s["delay_type"] = "random"; s["step"] = "target"
        await event.edit("🔗 أرسل المعرف الهدف (أو me للمحفوظات):")

    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0})
        await event.edit("⚡ أرسل معرف المصدر (مثلاً @channel):")
    elif d == b"stop": s["running"] = False; await event.answer("🛑 تم الإيقاف")
    elif d == b"reset": s.update({"sent": 0}); await event.answer("🗑️ تم تصفير العداد")

# ================= MENUS =================
async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل", b"transfer_menu")], [Button.inline("⚡ السرقة", b"steal")]]
    await event.respond("✅ الحساب جاهز:", buttons=btns)

async def show_transfer_menu(event):
    btns = [[Button.inline("📝 نقل فردي", b"new_transfer")],[Button.inline("📦 نقل تجميعي", b"batch_transfer")],[Button.inline("🗑️ ضبط العداد", b"reset"), Button.inline("🔙 رجوع", b"main_menu")]]
    await event.edit("📤 قائمة النقل:", buttons=btns)

# ================= ENGINE =================
async def run_engine(uid):
    s = state[uid]; client = s["client"]; mode = s["mode"]
    src = s.get("source", "me"); dst = s.get("target", "me")
    delay_type = s.get("delay_type", "random")
    batch = []
    
    try:
        total = (await client.get_messages(src, limit=0)).total
    except: total = "???"

    count = 0
    async for m in client.iter_messages(src, limit=None, reverse=True):
        if not s.get("running"): break
        if not m.media: continue 

        try:
            if mode in ["batch", "steal"]:
                batch.append(m)
                if len(batch) == 10:
                    await client.send_file(dst, batch)
                    count += 10; s["sent"] = count; batch.clear()
                    await s["status"].edit(f"📊 جاري النقل: {count} / {total}")
                    
                    # تطبيق التأخير في النقل التجميعي فقط
                    if mode == "batch":
                        wait = 10 if delay_type == "fixed" else random.randint(10, 19)
                        await asyncio.sleep(wait)
            else:
                await client.send_file(dst, m, caption=clean_caption(m.text))
                count += 1; s["sent"] = count
                await s["status"].edit(f"📊 جاري النقل: {count} / {total}")
                
                # تطبيق التأخير في النقل الفردي
                wait = 10 if delay_type == "fixed" else random.randint(10, 19)
                await asyncio.sleep(wait)
        
        except Exception as e:
            if "FloodWait" in str(e):
                wait_time = int(re.findall(r'\d+', str(e))[0])
                await s["status"].edit(f"⏳ حماية تليجرام! انتظار {wait_time} ثانية...")
                await asyncio.sleep(wait_time)
            continue
            
    if batch and s.get("running"): 
        await client.send_file(dst, batch); count += len(batch)
    await s["status"].edit(f"✅ اكتمل العمل!\nتم نقل {count} مقطع فيديو.")

bot.run_until_disconnected()
