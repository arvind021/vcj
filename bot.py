"""
Telegram Hybrid System
- Bot se accounts login kar sakte ho (phone + OTP bot mein dalo)
- Bot se sab control hoga

Requirements: pip install telethon python-telegram-bot
"""

import asyncio
import os
import logging
from telethon import TelegramClient
from telethon.tl.functions.phone import JoinGroupCallRequest, LeaveGroupCallRequest
from telethon.tl.functions.channels import GetFullChannelRequest, JoinChannelRequest, LeaveChannelRequest
from telethon.tl.functions.messages import GetFullChatRequest, ImportChatInviteRequest, DeleteChatUserRequest
from telethon.tl.types import InputGroupCall, Channel, Chat
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler

logging.basicConfig(level=logging.WARNING)

# ═══════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════
API_ID      = 12380656
API_HASH    = "d927c13beaaf5110f25c505b7c071273"
BOT_TOKEN   = "8777846753:AAFEBDqbOOIJqkf_mRY37SUdQOERvE4yu40"
ADMIN_ID    = 7302427268        # Apna Telegram User ID

SESSIONS_DIR = "sessions"
# ═══════════════════════════════════════════════════

os.makedirs(SESSIONS_DIR, exist_ok=True)
clients: list[TelegramClient] = []

# Login conversation states
PHONE, OTP, PASSWORD = range(3)

# Active login sessions (pending OTP)
pending_logins: dict = {}


# ─── Helpers ────────────────────────────────────────

def parse_link(link: str):
    link = link.strip()
    if link.startswith("@"):
        return "public", link[1:]
    for prefix in ["https://t.me/+", "https://t.me/joinchat/"]:
        if link.startswith(prefix):
            return "private", link[len(prefix):]
    if "t.me/" in link:
        return "public", link.split("t.me/")[-1].strip("/")
    return "public", link


async def get_active_call(client: TelegramClient, chat_id: int):
    try:
        entity = await client.get_entity(chat_id)
        if isinstance(entity, Channel):
            full = await client(GetFullChannelRequest(entity))
        elif isinstance(entity, Chat):
            full = await client(GetFullChatRequest(entity.id))
        else:
            return None
        call = full.full_chat.call
        if not call:
            return None
        return InputGroupCall(id=call.id, access_hash=call.access_hash)
    except:
        return None


def chat_label(entity) -> str:
    if isinstance(entity, Channel):
        return "📢 Channel" if entity.broadcast else "👥 Supergroup"
    elif isinstance(entity, Chat):
        return "👥 Group"
    return "❓"


async def load_all_sessions():
    loaded = 0
    for f in sorted(os.listdir(SESSIONS_DIR)):
        if not f.endswith(".session"):
            continue
        sname = f.replace(".session", "")
        path = os.path.join(SESSIONS_DIR, sname)
        try:
            c = TelegramClient(path, API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                clients.append(c)
                me = await c.get_me()
                print(f"  ✅ {me.first_name} (ID: {me.id})")
                loaded += 1
            else:
                await c.disconnect()
        except Exception as e:
            print(f"  ❌ {sname}: {e}")
    return loaded


# ─── Admin Check ────────────────────────────────────

def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


# ─── Login Conversation ──────────────────────────────

async def cmd_addaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot se naya account add karo"""
    if not is_admin(update):
        await update.message.reply_text("❌ Sirf admin ke liye.")
        return ConversationHandler.END

    await update.message.reply_text(
        "📱 *Naya Account Add Karo*\n\n"
        "Session naam bhejo (e.g. `acc1`, `acc2`)\n"
        "Ya /cancel karo",
        parse_mode="Markdown"
    )
    return PHONE


async def receive_session_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Session naam receive karo, phir phone maango"""
    if not is_admin(update):
        return ConversationHandler.END

    text = update.message.text.strip()

    # Check duplicate
    existing = [os.path.basename(c.session.filename).replace(".session", "") for c in clients]
    if text in existing:
        await update.message.reply_text(f"⚠️ `{text}` pehle se loaded hai! Doosra naam do.", parse_mode="Markdown")
        return PHONE

    context.user_data["session_name"] = text

    await update.message.reply_text(
        f"✅ Session naam: `{text}`\n\n"
        "📞 Ab phone number bhejo:\n"
        "Format: `+919876543210`",
        parse_mode="Markdown"
    )
    return OTP


async def receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Phone number receive karo, OTP bhejo"""
    if not is_admin(update):
        return ConversationHandler.END

    phone = update.message.text.strip()
    session_name = context.user_data.get("session_name", "account")
    path = os.path.join(SESSIONS_DIR, session_name)

    await update.message.reply_text(f"⏳ OTP bheja ja raha hai `{phone}` pe...", parse_mode="Markdown")

    try:
        client = TelegramClient(path, API_ID, API_HASH)
        await client.connect()
        result = await client.send_code_request(phone)

        # Pending login save karo
        pending_logins[update.effective_user.id] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": result.phone_code_hash,
            "session_name": session_name,
        }
        context.user_data["phone"] = phone

        await update.message.reply_text(
            "✅ OTP bheja gaya!\n\n"
            "📨 Telegram pe jo OTP aaya hai wo bhejo:\n"
            "Format: `12345`\n\n"
            "_(OTP sirf tum dekh sakte ho — private chat mein bhejo)_",
            parse_mode="Markdown"
        )
        return PASSWORD

    except Exception as e:
        await update.message.reply_text(f"❌ Error: `{e}`\n\nPhir try karo /addaccount", parse_mode="Markdown")
        return ConversationHandler.END


async def receive_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """OTP receive karo aur login complete karo"""
    if not is_admin(update):
        return ConversationHandler.END

    otp = update.message.text.strip().replace(" ", "")
    user_id = update.effective_user.id

    if user_id not in pending_logins:
        await update.message.reply_text("❌ Koi pending login nahi. /addaccount se shuru karo.")
        return ConversationHandler.END

    data = pending_logins[user_id]
    client = data["client"]
    phone = data["phone"]
    phone_code_hash = data["phone_code_hash"]
    session_name = data["session_name"]

    await update.message.reply_text("⏳ Login ho raha hai...")

    try:
        await client.sign_in(phone=phone, code=otp, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        clients.append(client)
        del pending_logins[user_id]

        await update.message.reply_text(
            f"✅ *Login Ho Gaya!*\n\n"
            f"• Naam    : {me.first_name} {me.last_name or ''}\n"
            f"• Username: @{me.username or 'N/A'}\n"
            f"• User ID : `{me.id}`\n"
            f"• Session : `{session_name}`\n\n"
            f"📊 Total loaded: *{len(clients)}*",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    except Exception as e:
        err = str(e)
        # 2FA password required
        if "PASSWORD_HASH_INVALID" in err or "two-step" in err.lower() or "SessionPasswordNeededError" in err:
            await update.message.reply_text(
                "🔐 *2FA Password Required*\n\n"
                "Apna Telegram 2FA password bhejo:",
                parse_mode="Markdown"
            )
            return PASSWORD + 1  # go to password state
        else:
            await update.message.reply_text(f"❌ OTP galat hai ya expire ho gaya.\n`{err}`\n\nPhir try: /addaccount", parse_mode="Markdown")
            await client.disconnect()
            del pending_logins[user_id]
            return ConversationHandler.END


async def receive_2fa_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """2FA password receive karo"""
    if not is_admin(update):
        return ConversationHandler.END

    password = update.message.text.strip()
    user_id = update.effective_user.id

    if user_id not in pending_logins:
        await update.message.reply_text("❌ Koi pending login nahi.")
        return ConversationHandler.END

    data = pending_logins[user_id]
    client = data["client"]
    session_name = data["session_name"]

    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        clients.append(client)
        del pending_logins[user_id]

        await update.message.reply_text(
            f"✅ *2FA Login Ho Gaya!*\n\n"
            f"• Naam    : {me.first_name}\n"
            f"• User ID : `{me.id}`\n"
            f"• Session : `{session_name}`\n\n"
            f"📊 Total loaded: *{len(clients)}*",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    except Exception as e:
        await update.message.reply_text(f"❌ Password galat hai.\n`{e}`", parse_mode="Markdown")
        await client.disconnect()
        del pending_logins[user_id]
        return ConversationHandler.END


async def cancel_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Login cancel karo"""
    user_id = update.effective_user.id
    if user_id in pending_logins:
        await pending_logins[user_id]["client"].disconnect()
        del pending_logins[user_id]
    await update.message.reply_text("❌ Login cancel ho gaya.")
    return ConversationHandler.END


# ─── Bot Commands ────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(
        f"🤖 *VC Userbot Controller*\n\n"
        f"Loaded accounts: *{len(clients)}*\n\n"
        "/addaccount — naya account login karo\n"
        "/sessions — saari IDs dekho\n"
        "/joingroupall — saare group join\n"
        "/joinvcall — saare VC join\n"
        "/leavevcall — saare VC leave\n"
        "/chatid — chat ID pao\n"
        "/help — puri list",
        parse_mode="Markdown"
    )


async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not clients:
        await update.message.reply_text("❌ Koi account loaded nahi.\n/addaccount se add karo.")
        return
    lines = [f"📋 *Loaded Accounts ({len(clients)})*\n"]
    for i, c in enumerate(clients, 1):
        try:
            m = await c.get_me()
            lines.append(f"{i}. {m.first_name} (@{m.username or 'N/A'}) — `{m.id}`")
        except:
            lines.append(f"{i}. (unavailable)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_joingroupall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /joingroupall `<link>`", parse_mode="Markdown")
        return
    link = context.args[0]
    ltype, identifier = parse_link(link)
    total = len(clients)
    msg = await update.message.reply_text(f"⏳ *{total} accounts* join ho rahe hain...", parse_mode="Markdown")
    results = []
    success = 0
    for i, c in enumerate(clients, 1):
        me = await c.get_me()
        try:
            if ltype == "private":
                await c(ImportChatInviteRequest(identifier))
            else:
                await c(JoinChannelRequest(identifier))
            results.append(f"✅ {me.first_name} — `{me.id}`")
            success += 1
        except Exception as e:
            err = str(e)
            if "USER_ALREADY_PARTICIPANT" in err or "already" in err.lower():
                results.append(f"✅ {me.first_name} — `{me.id}` (pehle se)")
                success += 1
            else:
                results.append(f"❌ {me.first_name} — {err[:40]}")
        await asyncio.sleep(2)
    await msg.edit_text(
        f"📋 *Group Join Complete*\n✅ *{success}/{total}*\n\n" + "\n".join(results),
        parse_mode="Markdown"
    )


async def cmd_leavegroupall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /leavegroupall `<chat_id>`", parse_mode="Markdown")
        return
    try:
        chat_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Valid chat_id dalo")
        return
    total = len(clients)
    msg = await update.message.reply_text(f"⏳ *{total} accounts* leave kar rahe hain...", parse_mode="Markdown")
    results = []
    success = 0
    for i, c in enumerate(clients, 1):
        me = await c.get_me()
        try:
            entity = await c.get_entity(chat_id)
            if isinstance(entity, Channel):
                await c(LeaveChannelRequest(entity))
            elif isinstance(entity, Chat):
                await c(DeleteChatUserRequest(entity.id, await c.get_input_entity("me")))
            results.append(f"✅ {me.first_name} — `{me.id}`")
            success += 1
        except Exception as e:
            results.append(f"❌ {me.first_name} — {str(e)[:40]}")
        await asyncio.sleep(1)
    await msg.edit_text(
        f"📋 *Group Leave Complete*\n✅ *{success}/{total}*\n\n" + "\n".join(results),
        parse_mode="Markdown"
    )


async def cmd_joinvcall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /joinvcall `<chat_id>`", parse_mode="Markdown")
        return
    try:
        chat_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Valid chat_id dalo")
        return
    total = len(clients)
    msg = await update.message.reply_text(f"⏳ *{total} accounts* VC join kar rahe hain...", parse_mode="Markdown")
    if clients:
        test = await get_active_call(clients[0], chat_id)
        if not test:
            await msg.edit_text("❌ Koi active VC nahi mili. Pehle voice chat start karo.")
            return
    results = []
    success = 0
    for i, c in enumerate(clients, 1):
        me = await c.get_me()
        try:
            call = await get_active_call(c, chat_id)
            if not call:
                results.append(f"⚠️ {me.first_name} — group mein nahi")
                continue
            await c(JoinGroupCallRequest(
                call=call,
                join_as=await c.get_input_entity("me"),
                params=None, muted=True, video_stopped=True,
            ))
            results.append(f"✅ {me.first_name} — `{me.id}`")
            success += 1
        except Exception as e:
            err = str(e)
            if "already" in err.lower():
                results.append(f"✅ {me.first_name} — `{me.id}` (already)")
                success += 1
            else:
                results.append(f"❌ {me.first_name} — {err[:40]}")
        await asyncio.sleep(1)
    await msg.edit_text(
        f"📋 *VC Join Complete*\n✅ *{success}/{total}*\n\n" + "\n".join(results),
        parse_mode="Markdown"
    )


async def cmd_leavevcall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /leavevcall `<chat_id>`", parse_mode="Markdown")
        return
    try:
        chat_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Valid chat_id dalo")
        return
    total = len(clients)
    msg = await update.message.reply_text(f"⏳ *{total} accounts* VC chhod rahe hain...", parse_mode="Markdown")
    results = []
    success = 0
    for i, c in enumerate(clients, 1):
        me = await c.get_me()
        try:
            call = await get_active_call(c, chat_id)
            if not call:
                results.append(f"⚠️ {me.first_name} — VC nahi mili")
                continue
            await c(LeaveGroupCallRequest(call=call))
            results.append(f"✅ {me.first_name} — `{me.id}`")
            success += 1
        except Exception as e:
            results.append(f"❌ {me.first_name} — {str(e)[:40]}")
        await asyncio.sleep(1)
    await msg.edit_text(
        f"📋 *VC Leave Complete*\n✅ *{success}/{total}*\n\n" + "\n".join(results),
        parse_mode="Markdown"
    )


async def cmd_loadall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    existing = [os.path.basename(c.session.filename).replace(".session", "") for c in clients]
    new_loaded = 0
    results = []
    for f in sorted(os.listdir(SESSIONS_DIR)):
        if not f.endswith(".session"):
            continue
        sname = f.replace(".session", "")
        if sname in existing:
            continue
        path = os.path.join(SESSIONS_DIR, sname)
        try:
            c = TelegramClient(path, API_ID, API_HASH)
            await c.connect()
            if await c.is_user_authorized():
                clients.append(c)
                me = await c.get_me()
                results.append(f"✅ {me.first_name} — `{me.id}`")
                new_loaded += 1
            else:
                await c.disconnect()
                results.append(f"⚠️ {sname} — authorized nahi")
        except Exception as e:
            results.append(f"❌ {sname} — {str(e)[:40]}")
    await update.message.reply_text(
        f"📂 *Reload Complete*\nNaye: *{new_loaded}* | Total: *{len(clients)}*\n\n" +
        ("\n".join(results) if results else "Koi naya session nahi mila."),
        parse_mode="Markdown"
    )


async def cmd_removeaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Usage: /removeaccount `<session_naam>`", parse_mode="Markdown")
        return
    sname = context.args[0].strip()
    for i, c in enumerate(clients):
        name = os.path.basename(c.session.filename).replace(".session", "")
        if name == sname:
            me = await c.get_me()
            await c.disconnect()
            clients.pop(i)
            await update.message.reply_text(
                f"✅ *Remove Ho Gaya*\n{me.first_name} — `{me.id}`\nTotal: *{len(clients)}*",
                parse_mode="Markdown"
            )
            return
    await update.message.reply_text(f"❌ `{sname}` nahi mila.", parse_mode="Markdown")


async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(
        f"ℹ️ *Chat Info*\n• Title: {chat.title or 'N/A'}\n• ID: `{chat.id}`\n• Type: {chat.type}",
        parse_mode="Markdown"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(
        f"🤖 *VC Userbot* — *{len(clients)} accounts*\n\n"
        "*👤 Account Login:*\n"
        "/addaccount — bot se naya account login karo\n"
        "/sessions — saari IDs\n"
        "/loadall — sessions folder reload\n"
        "/removeaccount `<naam>` — account hatao\n\n"
        "*📥 Group:*\n"
        "/joingroupall `<link>` — saare join\n"
        "/leavegroupall `<chat_id>` — saare leave\n\n"
        "*🎙️ Voice Chat:*\n"
        "/joinvcall `<chat_id>` — saare VC join\n"
        "/leavevcall `<chat_id>` — saare VC leave\n\n"
        "*ℹ️ Utils:*\n"
        "/chatid — chat ID pao\n\n"
        "💡 Chat ID pane ke liye group mein /chatid bhejo",
        parse_mode="Markdown"
    )


# ─── Main ───────────────────────────────────────────

async def main():
    print("\n📱 Existing sessions load ho rahe hain...")
    loaded = await load_all_sessions()
    print(f"\n🟢 {loaded} accounts ready\n")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Login conversation handler
    login_conv = ConversationHandler(
        entry_points=[CommandHandler("addaccount", cmd_addaccount)],
        states={
            PHONE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_session_name)],
            OTP:          [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_phone)],
            PASSWORD:     [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_otp)],
            PASSWORD + 1: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_2fa_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel_login)],
    )

    app.add_handler(login_conv)
    app.add_handler(CommandHandler("start",          cmd_start))
    app.add_handler(CommandHandler("help",           cmd_help))
    app.add_handler(CommandHandler("sessions",       cmd_sessions))
    app.add_handler(CommandHandler("joingroupall",   cmd_joingroupall))
    app.add_handler(CommandHandler("leavegroupall",  cmd_leavegroupall))
    app.add_handler(CommandHandler("joinvcall",      cmd_joinvcall))
    app.add_handler(CommandHandler("leavevcall",     cmd_leavevcall))
    app.add_handler(CommandHandler("loadall",        cmd_loadall))
    app.add_handler(CommandHandler("removeaccount",  cmd_removeaccount))
    app.add_handler(CommandHandler("chatid",         cmd_chatid))

    print("🤖 Bot chal raha hai!")
    print(f"   Accounts loaded : {len(clients)}")
    print(f"   Admin ID        : {ADMIN_ID}")
    print("   Ctrl+C se band karo\n")

    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    try:
        if clients:
            await asyncio.gather(*[c.run_until_disconnected() for c in clients])
        else:
            await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        print("\n⏹ Band ho raha hai...")
        await app.updater.stop()
        await app.stop()
        for c in clients:
            await c.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
