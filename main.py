import asyncio
import os
import re
import json
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from pyrogram import Client as PyroClient, enums

# ================= CONFIG =================
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

AUTH_CODES = {"25864mnb00", "20002000"}
AUTH_FILE = "authorized.txt"
AUTHORIZED_USERS = set()

if os.path.exists(AUTH_FILE):
    with open(AUTH_FILE) as f:
        try: AUTHORIZED_USERS = set(map(int, f.read().splitlines()))
        except: pass

bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)
state = {}
TEMP_SESSIONS = {}

# ================= ROUTER & LOGIC =================
@bot.on(events.NewMessage)
async def router(event):
    uid = event.sender_id
    text = (event.text or "").strip()
    s = state.setdefault(uid, {})

    if uid not in AUTHORIZED_USERS:
        if text in AUTH_CODES:
            AUTHORIZED_USERS.add(uid)
            with open(AUTH_FILE, "a") as f: f.write(f"{uid}\n")
            await event.respond("✅ تم الدخول، أرسل /start")
        else: await event.respond("🔐 أرسل رمز الدخول")
        return

    if text == "/start":
        s.clear()
        await event.respond("اختر طريقة الدخول:", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج سيشن", b"extract_session")],
            [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
        ])
        return

    # منطق الدخول (تكملة الخطوات)
    step = s.get("step")
    if step == "temp_phone":
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
            s["step"] = "main"; await show_main_menu(event)
        except SessionPasswordNeededError:
            s["step"] = "temp_2fa"; await event.respond("🔐 أرسل رمز 2FA")
        except Exception as e: await event.respond(f"❌ خطأ: {e}")
        return

    # (بقية خطوات النقل والسرقة تبقى كما هي في الكود السابق)

@bot.on(events.CallbackQuery)
async def cb(event):
    uid = event.sender_id
    s = state.setdefault(uid, {})
    d = event.data

    # --- إصلاح ميزة تسجيل الخروج المؤقت ---
    if d == b"clear_temp":
        if uid in TEMP_SESSIONS:
            try:
                await TEMP_SESSIONS[uid].log_out() # تسجيل الخروج من تليجرام
                await TEMP_SESSIONS[uid].disconnect()
            except: pass
            del TEMP_SESSIONS[uid]
        
        # مسح بيانات الجلسة من ذاكرة البوت تماماً
        s.pop("client", None)
        s.pop("raw_session", None)
        s.pop("step", None)
        
        await event.edit("✅ تم تسجيل الخروج بنجاح ومسح الجلسة مؤقتاً.\nيمكنك الآن الدخول بحساب آخر.", 
                         buttons=[[Button.inline("🔄 العودة للبداية", b"back_to_start")]])
        return

    if d == b"back_to_start":
        await event.edit("اختر طريقة الدخول:", buttons=[
            [Button.inline("🛡 الحسابات المحمية", b"sessions")],
            [Button.inline("📲 دخول مؤقت", b"temp")],
            [Button.inline("🔑 استخراج سيشن", b"extract_session")],
            [Button.inline("🧹 تسجيل خروج المؤقت", b"clear_temp")]
        ])
        return

    # (بقية الـ CallbackQuery تبقى كما هي للتعامل مع النقل والسرقة)

async def show_main_menu(event):
    await event.respond("اختر العملية:", buttons=[
        [Button.inline("📤 النقل", b"transfer_menu")],
        [Button.inline("⚡ السرقة", b"steal")],
        [Button.inline("🔓 السرقة المحمية", b"steal_protected")],
        [Button.inline("🧹 تنظيف الإدمن", b"clean_menu")]
    ])

# (بقية دوال النقل والسرقة run و clean_caption تبقى ثابتة)

bot.run_until_disconnected()
