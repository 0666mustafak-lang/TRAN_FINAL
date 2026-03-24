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
    # إذا كان الوضع نقل (مجنون أو آمن) المصدر هو الرسائل المحفوظة "me"
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
        if not m.video: continue

        # --- وضع السرقة التجميعي (من قناة للمحفوظات) ---
        if mode == "steal":
            batch.append(m.media)
            if len(batch) == 10:
                try:
                    await client.send_file("me", batch, caption="") 
                    s["sent"] += 10
                    await s["status"].edit(f"⚡ سرقة تجميعية: {s['sent']} / {total}")
                    batch.clear()
                except: pass
            continue 

        # --- وضع النقل (من المحفوظات للقناة الهدف) ---
        try:
            # إرسال الفيديو من محفوظاتك إلى dst (القناة الهدف)
            await client.send_file(dst, m.media, caption=clean_caption(m.text))
            s["sent"] += 1
            # تحديث العداد رقم برقم كما طلبت
            await s["status"].edit(f"📤 {mode}: {s['sent']} / {total}")
            await asyncio.sleep(delay)
        except FloodWaitError as f:
            if mode == "safe_transfer":
                await s["status"].edit(f"⏳ حماية: انتظار {f.seconds} ثانية...")
                await asyncio.sleep(f.seconds + 2)
            else: continue
        except Exception as e:
            print(f"Error: {e}")
            continue

    if batch and s.get("running") and mode == "steal":
        try:
            await client.send_file("me", batch, caption="")
            s["sent"] += len(batch)
        except: pass
    
    await s["status"].edit(f"✅ اكتمل النقل من المحفوظات!\n📦 الإجمالي: {s['sent']} / {total}")

# ================= ROUTER & MENUS =================
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
        await event.respond("📟 **نظام النقل والمزامنة**", buttons=[
            [Button.inline("🛡 الحسابات", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج", b"extract_session")]
        ])

    step = s.get("step")
    if step == "delay":
        s["delay"] = int(text) if text.isdigit() else 5
        s["step"] = "target"; await event.respond("🔗 أرسل يوزر القناة الهدف (التي ستستلم من محفوظاتك):")
    elif step == "target":
        s.update({"target": text, "running": True})
        s["status"] = await event.respond("🚀 جاري سحب المقاطع من رسائلك المحفوظة...")
        asyncio.create_task(run_engine(uid))
    elif step == "steal_link":
        s.update({"source": text, "running": True})
        s["status"] = await event.respond("⚡ جاري السرقة من القناة للمحفوظات...")
        asyncio.create_task(run_engine(uid))

@bot.on(events.CallbackQuery)
async def cb_handler(event):
    uid = event.sender_id; s = state.setdefault(uid, {}); d = event.data
    if d == b"main_menu": await show_main_menu(event)
    elif d == b"transfer_menu":
        btns = [[Button.inline("🔥 نقل مجنون (من المحفوظات)", b"crazy_t")], [Button.inline("🛡️ نقل آمن (من المحفوظات)", b"safe_t")], [Button.inline("🔙 رجوع", b"main_menu")]]
        await event.edit("اختر وضع النقل من رسائلك المحفوظة:", buttons=btns)
    elif d == b"crazy_t": s.update({"mode": "crazy_transfer", "step": "delay", "sent": 0}); await event.edit("🔥 وضع المجنون! كم ثانية تأخير بين مقطع ومقطع؟")
    elif d == b"safe_t": s.update({"mode": "safe_transfer", "step": "delay", "sent": 0}); await event.edit("🛡️ وضع الآمن! كم ثانية تأخير؟")
    elif d == b"steal": s.update({"mode": "steal", "step": "steal_link", "sent": 0}); await event.edit("⚡ سرقة (10+10) إلى المحفوظات.. أرسل رابط المصدر:")
    elif d == b"sessions":
        accs = await get_accounts()
        btns = [[Button.inline(f"👤 {n}", f"load_{k}".encode())] for k, n in accs]
        btns.append([Button.inline("🔙 رجوع", b"main_menu")])
        await event.edit("🛡 اختر الحساب:", buttons=btns)
    elif d.startswith(b"load_"):
        key = d.decode().replace("load_", ""); s["raw_session"] = os.environ[key]
        s["client"] = TelegramClient(StringSession(s["raw_session"]), API_ID, API_HASH); await s["client"].connect(); await show_main_menu(event)

async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل (من المحفوظات)", b"transfer_menu")], [Button.inline("⚡ السرقة (للمحفوظات)", b"steal")]]
    await (event.edit if isinstance(event, events.CallbackQuery) else event.respond)("✅ خيارات الحساب المتصل:", buttons=btns)

bot.run_until_disconnected()
