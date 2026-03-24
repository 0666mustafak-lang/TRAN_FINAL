import asyncio
import os
import re
import json
import random
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

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
        if k.startswith("TG_SESSION_"):
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
        else: await event.respond("🔐 أرسل رمز الدخول")
        return

    if text == "/start":
        s.clear()
        await event.respond("📟 **قائمة التحكم**", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🧹 خروج المؤقت", b"clear_temp")]
        ])
        return

    step = s.get("step")
    if step == "temp_phone":
        s["client"] = TelegramClient(StringSession(), API_ID, API_HASH)
        await s["client"].connect()
        try:
            sent = await s["client"].send_code_request(text)
            s.update({"phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
            await event.respond("🔑 كود التحقق:")
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
        
    elif step == "temp_code":
        try:
            await s["client"].sign_in(phone=s["phone"], code=text, phone_code_hash=s["hash"])
            await show_main_menu(event)
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"; await event.respond("🔐 رمز 2FA:")
        except Exception as e: await event.respond(f"❌ خطأ: {e}")

    elif step == "temp_2fa":
        await s["client"].sign_in(password=text)
        await show_main_menu(event)

    elif step == "target":
        s["target"] = text; s["running"] = True
        s["status"] = await event.respond("🚀 جاري البدء...")
        asyncio.create_task(run_engine(uid))

    elif step == "steal_link":
        s["source"] = text; s["running"] = True
        s["status"] = await event.respond("⚡ جاري السرقة...")
        asyncio.create_task(run_engine(uid))

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb(event):
    uid = event.sender_id; s = state.setdefault(uid, {}); d = event.data
    
    if d == b"sessions":
        accs = await get_accounts()
        if not accs: return await event.edit("❌ لا توجد حسابات مضافة")
        btns = [[Button.inline(n, f"load_{k}".encode())] for k, n in accs]
        await event.edit("🛡 اختر الحساب:", buttons=btns)
        
    elif d.startswith(b"load_"):
        key = d.decode().split("_")[1]
        s["client"] = TelegramClient(StringSession(os.environ[key]), API_ID, API_HASH)
        await s["client"].connect()
        await show_main_menu(event)

    elif d == b"temp": 
        s["step"] = "temp_phone"
        await event.edit("📲 أرسل رقم الهاتف مع مفتاح الدولة:")

    elif d == b"clear_temp":
        if "client" in s:
            await s["client"].disconnect()
            del s["client"]
        await event.edit("🧹 تم مسح الجلسة المؤقتة.")

    elif d == b"transfer_menu":
        await event.edit("📤 قائمة النقل:", buttons=[
            [Button.inline("⏱️ ثابت (10ث)", b"d_10"), Button.inline("🎲 متغير (10-19ث)", b"d_rnd")],
            [Button.inline("🔙 رجوع", b"main_menu")]
        ])

    elif d in [b"d_10", b"d_rnd"]:
        s["mode"] = "transfer"; s["sent"] = 0; s["last_id"] = 0
        s["delay_mode"] = "fixed" if d == b"d_10" else "random"
        s["step"] = "target"
        await event.edit("🔗 أرسل المعرف الهدف (أو me):")

    elif d == b"steal":
        s["mode"] = "steal"; s["sent"] = 0; s["last_id"] = 0; s["step"] = "steal_link"
        await event.edit("🔗 أرسل رابط القناة المصدر:")

    elif d == b"main_menu": await show_main_menu(event)
    elif d == b"stop": s["running"] = False; await event.answer("🛑 توقف")

# ================= MENUS =================
async def show_main_menu(event):
    btns = [[Button.inline("📤 النقل", b"transfer_menu")], [Button.inline("⚡ السرقة", b"steal")]]
    await event.respond("✅ الحساب متصل وجاهز:", buttons=btns)

# ================= ENGINE (نظام النقل المستقر) =================
async def run_engine(uid):
    s = state[uid]; c = s["client"]
    
    try:
        if s["mode"] == "transfer":
            src = await c.get_entity("me")
            dst = await c.get_entity(s["target"])
        else: # سرقة
            src = await c.get_entity(s["source"])
            dst = "me"

        batch = []
        # استخدام نظامك المستقر (min_id و reverse=True)
        async for m in c.iter_messages(src, min_id=s.get("last_id", 0), reverse=True):
            if not s.get("running"): break
            if not m.video: continue

            if s["mode"] == "steal":
                batch.append(m.video)
                if len(batch) == 10:
                    await c.send_file(dst, batch)
                    s["sent"] += 10; s["last_id"] = m.id; batch.clear()
                    await s["status"].edit(f"📊 تم نقل: {s['sent']}")
                continue

            # النقل الفردي
            await c.send_file(dst, m.video, caption=clean_caption(m.text))
            s["sent"] += 1; s["last_id"] = m.id
            await s["status"].edit(f"📊 تم نقل: {s['sent']}")
            
            wait = 10 if s.get("delay_mode") == "fixed" else random.randint(10, 19)
            await asyncio.sleep(wait)

        if batch and s.get("running"):
            await c.send_file(dst, batch); s["sent"] += len(batch)
            await s["status"].edit(f"📊 تم نقل: {s['sent']}")

        await s["status"].edit(f"✅ اكتمل بنجاح: {s['sent']}")
    except Exception as e:
        await s["status"].edit(f"❌ حدث خطأ أثناء العمل: {e}")

bot.run_until_disconnected()
