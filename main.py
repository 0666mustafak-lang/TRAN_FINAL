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

# ================= THE ENGINE (Simple & Strong) =================
async def run_engine(uid):
    s = state[uid]
    client = s["client"]
    mode = s["mode"]
    
    # تحديد المصدر والهدف بدقة
    if mode == "steal":
        src = s.get("source")
        dst = "me"
    else:
        src = "me"
        dst = s.get("target")

    s["running"] = True
    s["sent"] = 0
    batch = []
    
    # جلب العدد الإجمالي للتأكد أن القناة مقروءة
    try:
        m_info = await client.get_messages(src, limit=0)
        total = m_info.total
    except:
        total = "???"

    # حلقة السحب - بسيطة ومباشرة
    async for m in client.iter_messages(src, limit=None):
        if not s.get("running"): break
        if not m.media: continue

        # --- وضع السرقة (10+10) مجمعة ---
        if mode == "steal":
            batch.append(m.media)
            if len(batch) == 10:
                try:
                    await client.send_file(dst, batch, caption="")
                    s["sent"] += 10
                    await s["status"].edit(f"⚡ سرقة تجميعية: {s['sent']} / {total}")
                    batch = []
                except: pass
            continue

        # --- وضع النقل (مجنون أو آمن) فيديو فيديو ---
        try:
            await client.send_file(dst, m.media, caption=clean_caption(m.text))
            s["sent"] += 1
            # تحديث العداد كل رسالة لترى الحركة
            await s["status"].edit(f"📤 {mode}: {s['sent']} / {total}")
            await asyncio.sleep(s.get("delay", 1))
        except FloodWaitError as f:
            if mode == "safe_transfer":
                await s["status"].edit(f"⏳ حماية: انتظار {f.seconds} ثانية")
                await asyncio.sleep(f.seconds + 2)
            else:
                continue
        except:
            continue

    # إرسال أي ميديا متبقية في القائمة
    if batch and mode == "steal":
        await client.send_file(dst, batch, caption="")
        s["sent"] += len(batch)

    await s["status"].edit(f"✅ انتهى! الإجمالي: {s['sent']}")

# ================= INTERFACE =================
@bot.on(events.NewMessage)
async def router(event):
    uid = event.sender_id
    text = (event.text or "").strip()
    s = state.setdefault(uid, {})

    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            AUTHORIZED_USERS.add(uid)
            with open(AUTH_FILE, "a") as f: f.write(f"{uid}\n")
            await event.respond("✅ تفعيل بنجاح /start")
        return

    if text == "/start":
        btns = [
            [Button.inline("🛡 الحسابات", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp_login")],
            [Button.inline("🧹 خروج المؤقت", b"clear_temp")]
        ]
        await event.respond("📟 لوحة التحكم", buttons=btns)

    step = s.get("step")
    if step == "delay":
        s["delay"] = int(text) if text.isdigit() else 1
        s["step"] = "target"
        await event.respond("🎯 أرسل يوزر القناة الهدف:")
    elif step == "target":
        s["target"] = text
        s["status"] = await event.respond("🚀 جاري البدء من المحفوظات...")
        asyncio.create_task(run_engine(uid))
    elif step == "steal_src":
        s["source"] = text
        s["status"] = await event.respond("⚡ جاري سرقة القناة للمحفوظات...")
        asyncio.create_task(run_engine(uid))
    
    elif step == "phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        s["client"] = c
        await c.connect()
        sent = await c.send_code_request(text)
        s.update({"ph": text, "hash": sent.phone_code_hash, "step": "code"})
        await event.respond("🔑 الكود:")
    elif step == "code":
        try:
            await s["client"].sign_in(s["ph"], text, phone_code_hash=s["hash"])
            await show_main_menu(event)
        except Telethon2FA:
            s["step"] = "2fa"
            await event.respond("🔐 رمز التحقق:")
    elif step == "2fa":
        await s["client"].sign_in(password=text)
        await show_main_menu(event)

@bot.on(events.CallbackQuery)
async def cb_handler(event):
    uid = event.sender_id
    s = state.setdefault(uid, {})
    d = event.data

    if d == b"main_menu": await show_main_menu(event)
    elif d == b"temp_login":
        s["step"] = "phone"
        await event.edit("📱 أرسل الرقم مع مفتاح الدولة:")
    elif d == b"clear_temp":
        if "client" in s: await s["client"].disconnect(); del s["client"]
        await event.answer("🧹 تم المسح", alert=True)
    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_src"})
        await event.edit("⚡ أرسل رابط القناة المصدر (للمحفوظات):")
    elif d == b"crazy_t":
        s.update({"mode": "crazy_transfer", "step": "delay"})
        await event.edit("🔥 نقل مجنون! كم ثانية تأخير؟")
    elif d == b"safe_t":
        s.update({"mode": "safe_transfer", "step": "delay"})
        await event.edit("🛡 نقل آمن! كم ثانية تأخير؟")
    elif d == b"sessions":
        accs = await get_accounts()
        btns = [[Button.inline(f"👤 {n}", f"load_{k}".encode())] for k, n in accs]
        await event.edit("🛡 اختر حسابك:", buttons=btns)
    elif d.startswith(b"load_"):
        key = d.decode().replace("load_", "")
        s["client"] = TelegramClient(StringSession(os.environ[key]), API_ID, API_HASH)
        await s["client"].connect()
        await show_main_menu(event)

async def show_main_menu(event):
    btns = [
        [Button.inline("📤 نقل (من المحفوظات)", b"crazy_t"), Button.inline("🛡 نقل آمن", b"safe_t")],
        [Button.inline("⚡ سرقة (للمحفوظات)", b"steal")]
    ]
    await (event.edit if isinstance(event, events.CallbackQuery) else event.respond)("✅ اختر العملية:", buttons=btns)

bot.run_until_disconnected()
