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
        with open(AUTH_FILE) as f:
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
    src = s.get("source", "me"); dst = s.get("target", "me")
    batch = []; s["running"] = True; delay = s.get("delay", 5)
    
    try:
        m_info = await client.get_messages(src, limit=0)
        total = m_info.total
    except: total = "???"

    async for m in client.iter_messages(src, limit=None):
        if not s.get("running"): break
        if not m.video: continue

        # --- نظام السرقة التجميعي (10+10) ---
        if mode == "steal":
            batch.append(m.media)
            if len(batch) == 10:
                try:
                    await client.send_file(dst, batch, caption="") 
                    s["sent"] += 10
                    await s["status"].edit(f"⚡ سرقة (10+10): {s['sent']} / {total}")
                    batch = []
                except FloodWaitError as f:
                    await asyncio.sleep(f.seconds + 2)
                except: pass
            continue # تخطي بقية الحلقة للسرقة

        # --- نظام النقل (آمن أو مجنون) ---
        try:
            await client.send_file(dst, m.media, caption=clean_caption(m.text))
            s["sent"] += 1
            if s["sent"] % 2 == 0:
                await s["status"].edit(f"📤 {mode}: {s['sent']} / {total}")
            await asyncio.sleep(delay)
        except FloodWaitError as f:
            if mode == "safe_transfer": # نظام الحماية يعمل هنا فقط
                await s["status"].edit(f"⏳ حماية: سأنتظر {f.seconds} ثانية...")
                await asyncio.sleep(f.seconds + 5)
            else: # في النقل المجنون نتخطى الخطأ ونكمل فوراً
                continue
        except: continue

    if batch and s.get("running"):
        try: await client.send_file(dst, batch, caption=""); s["sent"] += len(batch)
        except: pass
    
    await s["status"].edit(f"✅ تم الانتهاء!\n📦 الإجمالي: {s['sent']}")

# ================= ROUTER & CALLBACKS =================
@bot.on(events.NewMessage)
async def router(event):
    uid = event.sender_id; text = (event.text or "").strip(); s = state.setdefault(uid, {})
    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            AUTHORIZED_USERS.add(uid)
            with open(AUTH_FILE, "a") as f: f.write(f"{uid}\n")
            await event.respond("✅ تم التفعيل، أرسل /start")
        else: await event.respond("🔐 أرسل رمز الدخول:")
        return

    if text == "/start":
        await event.respond("📟 **نظام التحكم**", buttons=[
            [Button.inline("🛡 الحسابات", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج", b"extract_session")],
            [Button.inline("🧹 خروج المؤقت", b"clear_temp")]
        ])
        return

    step = s.get("step")
    if step == "delay":
        s["delay"] = int(text) if text.isdigit() else 5
        s["step"] = "target"; await event.respond("🔗 أرسل المعرف الهدف:")
    elif step == "target":
        s.update({"target": text, "running": True})
        s["status"] = await event.respond("🚀 جاري التحضير...")
        asyncio.create_task(run_engine(uid))
    elif step == "steal_link":
        s.update({"source": text, "target": "me", "running": True})
        s["status"] = await event.respond("⚡ جاري السرقة...")
        asyncio.create_task(run_engine(uid))
    
    # --- نظام تسجيل الدخول (نفس منطقك الأصلي) ---
    elif step == "ex_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH); s["ex_c"] = c; await c.connect()
        sent = await c.send_code_request(text); s.update({"ex_p": text, "ex_h": sent.phone_code_hash, "step": "ex_code"})
        await event.respond("🔑 كود الاستخراج:")
    elif step == "ex_code":
        try: await s["ex_c"].sign_in(s["ex_p"], text, phone_code_hash=s["ex_h"]); await event.respond(f"✅ السيشن:\n`{s['ex_c'].session.save()}`")
        except Telethon2FA: s["step"] = "ex_2fa"; await event.respond("🔐 2FA:")
    elif step == "ex_2fa":
        await s["ex_c"].sign_in(password=text); await event.respond(f"✅ السيشن:\n`{s['ex_c'].session.save()}`")

@bot.on(events.CallbackQuery)
async def cb_handler(event):
    uid = event.sender_id; s = state.setdefault(uid, {}); d = event.data
    if d == b"main_menu": await show_main_menu(event)
    elif d == b"transfer_menu":
        btns = [[Button.inline("🔥 نقل مجنون (بدون حماية)", b"crazy_t")], [Button.inline("🛡️ نقل آمن (مع حماية)", b"safe_t")], [Button.inline("🔙 رجوع", b"main_menu")]]
        await event.edit("اختر نوع النقل:", buttons=btns)
    elif d == b"crazy_t": s.update({"mode": "crazy_transfer", "step": "delay", "sent": 0}); await event.edit("🔥 وضع المجنون! كم ثانية تأخير؟")
    elif d == b"safe_t": s.update({"mode": "safe_transfer", "step": "delay", "sent": 0}); await event.edit("🛡️ وضع الآمن! كم ثانية تأخير؟")
    elif d == b"steal": s.update({"mode": "steal", "step": "steal_link", "sent": 0}); await event.edit("⚡ سرقة (10+10).. أرسل المصدر:")
    elif d == b"sessions":
        accs = await get_accounts()
        btns = [[Button.inline(f"👤 {n}", f"load_{k}".encode())] for k, n in accs]
        btns.append([Button.inline("🔙 رجوع", b"/start")])
        await event.edit("🛡 اختر الحساب:", buttons=btns)
    elif d.startswith(b"load_"):
        key = d.decode().replace("load_", ""); s["raw_session"] = os.environ[key]
        s["client"] = TelegramClient(StringSession(s["raw_session"]), API_ID, API_HASH); await s["client"].connect(); await show_main_menu(event)
    elif d == b"stop": s["running"] = False; await event.answer("🛑 تم الإيقاف")

async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل", b"transfer_menu")], [Button.inline("⚡ السرقة (10+10)", b"steal")]]
    await (event.edit if isinstance(event, events.CallbackQuery) else event.respond)("✅ خيارات الحساب:", buttons=btns)

bot.run_until_disconnected()
