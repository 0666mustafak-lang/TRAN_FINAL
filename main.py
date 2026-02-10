import asyncio
import os
import re
import json
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PasswordHashInvalidError

# ================= CONFIG =================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

AUTH_CODES = {"25864mnb00", "20002000"}

# ================= BOT =================
bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

state = {}
TEMP_SESSIONS = {}

# ================= HELPERS =================
def clean_caption(txt):
    return re.sub(r'@\w+|https?://\S+', '', txt or '')

async def show_main_menu(event):
    await event.respond(
        "🔓 تم تسجيل الدخول بنجاح! اختر العملية:",
        buttons=[
            [Button.inline("📤 قائمة النقل", b"transfer_menu")],
            [Button.inline("⚡ سرقة عادية", b"steal")],
            [Button.inline("🔓 سرقة محمية", b"steal_protected")]
        ]
    )

# ================= MESSAGE ROUTER =================
@bot.on(events.NewMessage)
async def router(event):
    uid = event.sender_id
    text = (event.text or "").strip()
    s = state.setdefault(uid, {})

    if text == "/start":
        if uid in TEMP_SESSIONS:
            try: await TEMP_SESSIONS[uid].disconnect()
            except: pass
        s.clear()
        await event.respond("طريقة الدخول:", buttons=[
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🧹 تنظيف", b"clear_temp")]
        ])
        return

    step = s.get("step")

    # --- إرسال الرقم ---
    if step == "temp_phone":
        c = TelegramClient(StringSession(), API_ID, API_HASH)
        TEMP_SESSIONS[uid] = c
        await c.connect()
        try:
            sent = await c.send_code_request(text)
            s.update({"client": c, "phone": text, "hash": sent.phone_code_hash, "step": "temp_code"})
            await event.respond("🔑 أرسل الكود:")
        except Exception as e:
            await event.respond(f"❌ خطأ: {e}")
        return

    # --- إرسال الكود ---
    if step == "temp_code":
        c = s.get("client")
        try:
            await c.sign_in(phone=s["phone"], code=text, phone_code_hash=s["hash"])
            s["step"] = "main"
            await show_main_menu(event)
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"
            await event.respond("🔐 الحساب محمي، أرسل كلمة السر (2FA):")
        except Exception:
            if await c.is_user_authorized(): # فحص إذا نجح الدخول فعلياً
                s["step"] = "main"
                await show_main_menu(event)
            else:
                await event.respond("⚠️ الكود خطأ، تأكد منه.")
        return

    # --- إرسال كلمة السر (الحل الجذري هنا) ---
    if step == "temp_2fa":
        c = s.get("client")
        try:
            # محاولة تسجيل الدخول بكلمة السر
            await c.sign_in(password=text)
            s["step"] = "main"
            await show_main_menu(event)
        except PasswordHashInvalidError:
            await event.respond("❌ كلمة السر غير صحيحة، أعد إرسالها:")
        except Exception as e:
            # إذا ظهر أي خطأ آخر، نتأكد هل الحساب فتح أم لا
            if await c.is_user_authorized():
                s["step"] = "main"
                await show_main_menu(event)
            else:
                await event.respond(f"⚠️ فشل الدخول: {e}")
        return

    # --- بقية ميزات النقل ---
    if step == "delay":
        s["delay"] = int(text) if text.isdigit() else 10
        s["step"] = "target"
        await event.respond("🔗 أرسل الهدف:")
        return

    if step == "target" or step == "steal_link":
        if step == "steal_link": s["source"] = text
        else: s["target"] = text
        s["running"] = True
        s["status"] = await event.respond("🚀 بدء العمل...", buttons=[[Button.inline("⏹️ إيقاف", b"stop")]])
        asyncio.create_task(run(uid))
        return

# ================= CALLBACKS =================
@bot.on(events.CallbackQuery)
async def cb(event):
    uid = event.sender_id
    s = state.setdefault(uid, {})
    d = event.data

    if d == b"temp":
        s["step"] = "temp_phone"
        await event.respond("📲 أرسل الرقم:")
    elif d == b"clear_temp":
        if uid in TEMP_SESSIONS:
            try: await TEMP_SESSIONS[uid].disconnect()
            except: pass
            del TEMP_SESSIONS[uid]
        s.clear()
        await event.respond("🧹 تم التنظيف.")
    elif d == b"transfer_menu":
        await event.respond("قائمة النقل:", buttons=[
            [Button.inline("📤 فردي", b"new_transfer")],
            [Button.inline("📦 تجميعي", b"batch_transfer")]
        ])
    elif d == b"new_transfer":
        s.update({"mode": "transfer", "step": "delay", "sent": 0})
        await event.respond("⏱️ أرسل التأخير:")
    elif d == b"batch_transfer":
        s.update({"mode": "batch_transfer", "step": "delay", "sent": 0})
        await event.respond("⏱️ أرسل التأخير:")
    elif d == b"steal":
        s.update({"mode": "steal", "step": "steal_link", "sent": 0})
        await event.respond("🔗 أرسل المصدر:")
    elif d == b"stop":
        s["running"] = False

# ================= RUN LOGIC =================
async def run(uid):
    s = state[uid]
    c = s["client"]
    try:
        if s["mode"].startswith("steal"):
            src = await c.get_entity(s["source"])
            dst = "me"
        else:
            src = await c.get_entity("me")
            dst = await c.get_entity(s["target"])

        batch = []
        async for m in c.iter_messages(src, reverse=True):
            if not s.get("running"): break
            if not m.video: continue

            if s["mode"] == "batch_transfer":
                batch.append(m.video)
                if len(batch) == 10:
                    await c.send_file(dst, batch)
                    s["sent"] += 10
                    await s["status"].edit(f"📦 تم نقل {s['sent']}")
                    batch.clear()
                continue

            await c.send_file(dst, m.video, caption=clean_caption(m.text))
            s["sent"] += 1
            await s["status"].edit(f"📊 تم نقل: {s['sent']}")
            await asyncio.sleep(s.get("delay", 10))

        if batch: await c.send_file(dst, batch)
        await s["status"].edit("✅ انتهى.")
    except Exception as e:
        await bot.send_message(uid, f"❌ خطأ: {e}")

bot.run_until_disconnected()
