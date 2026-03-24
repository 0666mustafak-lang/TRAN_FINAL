import os, asyncio, re
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError as Telethon2FA, FloodWaitError

# ================= CONFIG =================
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"

def load_authorized():
    if os.path.exists(AUTH_FILE):
        with open(AUTH_FILE, "r") as f:
            try: return set(map(int, f.read().splitlines()))
            except: return set()
    return set()

AUTHORIZED_USERS = load_authorized()
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}

def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def get_accounts():
    accs = []
    keys = sorted([k for k in os.environ.keys() if k.startswith("TG_SESSION_")])
    for k in keys:
        try:
            c = TelegramClient(StringSession(os.environ[k]), API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                me = await c.get_me()
                accs.append((k, me.first_name or k))
            await c.disconnect()
        except: continue
    return accs

# ================= THE POWER ENGINE =================
async def run_engine(uid):
    s = state[uid]; client = s["client"]; mode = s["mode"]
    src = "me" if "transfer" in mode else s.get("source", "me")
    dst = s.get("target", "me")
    
    batch = []; s["running"] = True; delay = s.get("delay", 5)
    s["sent"] = 0 
    
    try:
        m_info = await client.get_messages(src, limit=0)
        total = m_info.total
    except: total = "???"

    async for m in client.iter_messages(src, limit=None):
        if not s.get("running"): break
        if not m.media or (not m.video and not m.document): continue

        # --- وضع السرقة التجميعي (إلى المحفوظات) ---
        if mode == "steal":
            batch.append(m.media)
            if len(batch) == 10:
                try:
                    await client.send_file("me", batch, caption="") 
                    s["sent"] += 10
                    await s["status"].edit(f"⚡ سرقة تجميعية: {s['sent']} / {total}")
                    batch.clear()
                    await asyncio.sleep(0.5)
                except: pass
            continue 

        # --- وضع النقل (من المحفوظات للهدف) ---
        try:
            await client.send_file(dst, m.media, caption=clean_caption(m.text))
            s["sent"] += 1
            # تحديث العداد رقم برقم (تحديث لحظي)
            await s["status"].edit(f"📤 {mode}: {s['sent']} / {total}")
            await asyncio.sleep(delay)
        except FloodWaitError as f:
            if mode == "safe_transfer":
                await s["status"].edit(f"⏳ حماية: انتظار {f.seconds} ثانية...")
                await asyncio.sleep(f.seconds + 2)
            else: 
                await asyncio.sleep(1)
                continue
        except: continue

    if batch and s.get("running") and mode == "steal":
        try:
            await client.send_file("me", batch, caption="")
            s["sent"] += len(batch)
        except: pass
    
    await s["status"].edit(f"✅ اكتملت العملية!\n📦 الإجمالي: {s['sent']} / {total}")

# ================= ROUTER & CALLBACKS =================
@bot.on(events.NewMessage)
async def router(event):
    uid = event.sender_id; text = (event.text or "").strip(); s = state.setdefault(uid, {})
    
    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            AUTHORIZED_USERS.add(uid)
            with open(AUTH_FILE, "a") as f: f.write(f"{uid}\n")
            await event.respond("✅ تم التفعيل، أرسل /start")
        else: await event.respond("🔐 أرسل رمز الدخول:"); return

    if text == "/start":
        await event.respond("📟 **نظام التحكم الشامل**", buttons=[
            [Button.inline("🛡 الحسابات", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp_login")],
            [Button.inline("🔑 استخراج سيشن", b"extract_session")],
            [Button.inline("🧹 خروج المؤقت", b"clear_temp")]
        ])

    step = s.get("step")
    if step == "delay":
        s["delay"] = int(text) if text.isdigit() else 5
        s["step"] = "target"; await event.respond("🔗 أرسل يوزر القناة الهدف:")
    elif step == "target":
        s.update({"target": text, "running": True})
        s["status"] = await event.respond("🚀 جاري البدء...")
        asyncio.create_task(run_engine(uid))
    elif step == "steal_link":
        s.update({"source": text, "running": True})
        s["status"] = await event.respond("⚡ جاري السرقة التجميعية...")
        asyncio.create_task(run_engine(uid))
    
    elif step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH); s["client"] = c; await c.connect()
        sent = await c.send_code_request(text); s.update({"phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
        await event.respond("🔐 كود التحقق:")
    elif step == "temp_code":
        try: await s["client"].sign_in(s["phone"], text, phone_code_hash=s["hash"]); await show_main_menu(event)
        except Telethon2FA: s["step"] = "temp_2fa"; await event.respond("🔐 رمز 2FA:")
    elif step == "temp_2fa":
        await s["client"].sign_in(password=text); await show_main_menu(event)

@bot.on(events.CallbackQuery)
async def cb_handler(event):
    uid = event.sender_id; s = state.setdefault(uid, {}); d = event.data
    if d == b"main_menu": await show_main_menu(event)
    elif d == b"temp_login": s["step"] = "temp_phone"; await event.edit("📱 أرسل رقم الهاتف مع مفتاح الدولة:")
    elif d == b"clear_temp": 
        if "client" in s: await s["client"].disconnect(); del s["client"]
        await event.answer("🧹 تم تسجيل الخروج من الحساب المؤقت", alert=True)
    elif d == b"transfer_menu":
        btns = [[Button.inline("🔥 نقل مجنون", b"crazy_t")], [Button.inline("🛡️ نقل آمن", b"safe_t")], [Button.inline("🔙 رجوع", b"main_menu")]]
        await event.edit("اختر وضع النقل من المحفوظات للهدف:", buttons=btns)
    elif d == b"crazy_t": s.update({"mode": "crazy_transfer", "step": "delay", "sent": 0}); await event.edit("🔥 وضع المجنون! كم ثانية تأخير؟")
    elif d == b"safe_t": s.update({"mode": "safe_transfer", "step": "delay", "sent": 0}); await event.edit("🛡️ وضع الآمن! كم ثانية تأخير؟")
    elif d == b"steal": s.update({"mode": "steal", "step": "steal_link", "sent": 0}); await event.edit("⚡ سرقة (10+10) للمحفوظات.. أرسل المصدر:")
    elif d == b"sessions":
        accs = await get_accounts()
        btns = [[Button.inline(f"👤 {n}", f"load_{k}".encode())] for k, n in accs]
        btns.append([Button.inline("🔙 رجوع", b"main_menu")])
        await event.edit("🛡 اختر الحساب:", buttons=btns)
    elif d.startswith(b"load_"):
        key = d.decode().replace("load_", ""); s["raw_session"] = os.environ[key]
        s["client"] = TelegramClient(StringSession(s["raw_session"]), API_ID, API_HASH); await s["client"].connect(); await show_main_menu(event)
    elif d == b"stop": s["running"] = False; await event.answer("🛑 توقف")

async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل (من المحفوظات)", b"transfer_menu")], [Button.inline("⚡ السرقة (للمحفوظات)", b"steal")], [Button.inline("🛑 إيقاف", b"stop")]]
    if isinstance(event, events.CallbackQuery): await event.edit("✅ خيارات الحساب المتصل:", buttons=btns)
    else: await event.respond("✅ خيارات الحساب المتصل:", buttons=btns)

bot.run_until_disconnected()
