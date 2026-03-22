"""
Telegram Hybrid System
- Telegram Bot (BotFather token) = Controller/Admin panel
- Userbot sessions = actual workers (VC join/leave/group join)

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
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)

# ═══════════════════════════════════════════════════
# CONFIG — sirf yahan edit karo
# ═══════════════════════════════════════════════════
API_ID      = 123456              # my.telegram.org
API_HASH    = "your_api_hash"     # my.telegram.org
BOT_TOKEN   = "your_bot_token"    # BotFather se
ADMIN_ID    = 123456789           # Apna Telegram User ID (bot sirf isko manega)

SESSIONS_DIR = "sessions"         # .session files yahan
# ═══════════════════════════════════════════════════

os.makedirs(SESSIONS_DIR, exist_ok=True)
clients: list[TelegramClient] = []


# ─── Userbot Helpers ────────────────────────────────

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
    """sessions/ folder se saari .session files load karo"""
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


async def add_new_session(session_name: str):
    """Nayi session interactively banao"""
    path = os.path.join(SESSIONS_DIR, session_name)
    c = TelegramClient(path, API_ID, API_HASH)
    await c.start()  # terminal mein OTP maangega
    me = await c.get_me()
    clients.append(c)
    return me


# ─── Admin Check ────────────────────────────────────

def admin_only(func):
    """Sirf ADMIN_ID wala user commands use kar sakta hai"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("❌ Ye bot sirf admin ke liye hai.")
            return
        await func(update, context)
    return wrapper


# ─── Bot Commands ────────────────────────────────────

@admin_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 *VC Userbot Controller*\n\n"
        f"Loaded accounts: *{len(clients)}*\n\n"
        "*Commands:*\n"
        "/sessions — saari loaded IDs\n"
        "/joingroupall `<link>` — saare accounts group join\n"
        "/leavegroupall `<chat_id>` — saare accounts group leave\n"
        "/joinvcall `<chat_id>` — saare accounts VC join\n"
        "/leavevcall `<chat_id>` — saare accounts VC leave\n"
        "/addaccount `<naam>` — naya account add (terminal OTP)\n"
        "/loadall — sessions folder reload\n"
        "/help — commands list",
        parse_mode="Markdown"
    )


@admin_only
async def cmd_sessions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not clients:
        await update.message.reply_text("❌ Koi account loaded nahi hai.\n/addaccount se add karo.")
        return
    lines = [f"📋 *Loaded Accounts ({len(clients)} total)*\n"]
    for i, c in enumerate(clients, 1):
        try:
            m = await c.get_me()
            sname = os.path.basename(c.session.filename).replace(".session", "")
            lines.append(f"{i}. {m.first_name} (@{m.username or 'N/A'}) — `{m.id}`")
        except:
            lines.append(f"{i}. (unavailable)")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def cmd_joingroupall(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                results.append(f"❌ {me.first_name} — `{me.id}` → {err[:50]}")
        await asyncio.sleep(2)

    await msg.edit_text(
        f"📋 *Group Join Complete*\n"
        f"✅ Joined: *{success}/{total}*\n\n" +
        "\n".join(results),
        parse_mode="Markdown"
    )


@admin_only
async def cmd_leavegroupall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /leavegroupall `<chat_id>`\n\nChat ID pane ke liye group mein /chatid bhejo.",
            parse_mode="Markdown"
        )
        return

    try:
        chat_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Valid chat_id dalo (number hona chahiye)")
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
            results.append(f"❌ {me.first_name} — `{me.id}` → {str(e)[:50]}")
        await asyncio.sleep(1)

    await msg.edit_text(
        f"📋 *Group Leave Complete*\n"
        f"✅ Left: *{success}/{total}*\n\n" +
        "\n".join(results),
        parse_mode="Markdown"
    )


@admin_only
async def cmd_joinvcall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /joinvcall `<chat_id>`\n\nChat ID pane ke liye: /chatid",
            parse_mode="Markdown"
        )
        return

    try:
        chat_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Valid chat_id dalo")
        return

    total = len(clients)
    msg = await update.message.reply_text(f"⏳ *{total} accounts* VC join kar rahe hain...", parse_mode="Markdown")

    # Check VC active hai
    if clients:
        test_call = await get_active_call(clients[0], chat_id)
        if not test_call:
            await msg.edit_text("❌ Koi active VC nahi mili. Pehle voice chat start karo.")
            return

    results = []
    success = 0
    for i, c in enumerate(clients, 1):
        me = await c.get_me()
        try:
            call = await get_active_call(c, chat_id)
            if not call:
                results.append(f"⚠️ {me.first_name} — group mein nahi hai")
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
                results.append(f"❌ {me.first_name} — `{me.id}` → {err[:50]}")
        await asyncio.sleep(1)

    await msg.edit_text(
        f"📋 *VC Join Complete*\n"
        f"✅ Joined: *{success}/{total}*\n\n" +
        "\n".join(results),
        parse_mode="Markdown"
    )


@admin_only
async def cmd_leavevcall(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            results.append(f"❌ {me.first_name} — `{me.id}` → {str(e)[:50]}")
        await asyncio.sleep(1)

    await msg.edit_text(
        f"📋 *VC Leave Complete*\n"
        f"✅ Left: *{success}/{total}*\n\n" +
        "\n".join(results),
        parse_mode="Markdown"
    )


@admin_only
async def cmd_addaccount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /addaccount `<session_naam>`\n\nExample: /addaccount acc5\n\n"
            "⚠️ Terminal mein OTP daalna hoga.",
            parse_mode="Markdown"
        )
        return
    sname = context.args[0].strip()
    # Check duplicate
    existing = [os.path.basename(c.session.filename).replace(".session", "") for c in clients]
    if sname in existing:
        await update.message.reply_text(f"⚠️ `{sname}` pehle se loaded hai!", parse_mode="Markdown")
        return
    await update.message.reply_text(f"⏳ `{sname}` add ho raha hai...\n⚠️ Terminal mein phone + OTP dalo!", parse_mode="Markdown")
    try:
        me = await add_new_session(sname)
        await update.message.reply_text(
            f"✅ *Account Add Ho Gaya!*\n"
            f"• Naam: {me.first_name}\n"
            f"• ID: `{me.id}`\n"
            f"• Total: *{len(clients)}*",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Add nahi ho saka: `{e}`", parse_mode="Markdown")


@admin_only
async def cmd_loadall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    existing = [os.path.basename(c.session.filename).replace(".session", "") for c in clients]
    new_loaded = 0
    results = []
    for f in sorted(os.listdir(SESSIONS_DIR)):
        if not f.endswith(".session"):
            continue
        sname = f.replace(".session", "")
        if sname in existing:
            results.append(f"⏭️ {sname} — already loaded")
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
        f"📂 *Reload Complete*\n"
        f"Naye: *{new_loaded}* | Total: *{len(clients)}*\n\n" +
        "\n".join(results[:20]),
        parse_mode="Markdown"
    )


@admin_only
async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Chat ID pata karne ke liye — group mein /chatid bhejo"""
    chat = update.effective_chat
    await update.message.reply_text(
        f"ℹ️ *Chat Info*\n"
        f"• Title: {chat.title or 'N/A'}\n"
        f"• Chat ID: `{chat.id}`\n"
        f"• Type: {chat.type}",
        parse_mode="Markdown"
    )


@admin_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🤖 *VC Userbot Controller*\n"
        f"Loaded: *{len(clients)} accounts*\n\n"
        "*📥 Group:*\n"
        "/joingroupall `<link>` — saare join\n"
        "/leavegroupall `<chat_id>` — saare leave\n\n"
        "*🎙️ Voice Chat:*\n"
        "/joinvcall `<chat_id>` — saare VC join\n"
        "/leavevcall `<chat_id>` — saare VC leave\n\n"
        "*👤 Accounts:*\n"
        "/sessions — saari IDs\n"
        "/addaccount `<naam>` — naya add\n"
        "/loadall — folder reload\n\n"
        "*ℹ️ Utils:*\n"
        "/chatid — is chat ka ID pao\n"
        "/start — home\n\n"
        "💡 *chat\\_id pane ke liye group mein /chatid bhejo*",
        parse_mode="Markdown"
    )


# ─── Main ───────────────────────────────────────────

async def run_bot():
    """Telegram bot run karo"""
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",          cmd_start))
    app.add_handler(CommandHandler("help",           cmd_help))
    app.add_handler(CommandHandler("sessions",       cmd_sessions))
    app.add_handler(CommandHandler("joingroupall",   cmd_joingroupall))
    app.add_handler(CommandHandler("leavegroupall",  cmd_leavegroupall))
    app.add_handler(CommandHandler("joinvcall",      cmd_joinvcall))
    app.add_handler(CommandHandler("leavevcall",     cmd_leavevcall))
    app.add_handler(CommandHandler("addaccount",     cmd_addaccount))
    app.add_handler(CommandHandler("loadall",        cmd_loadall))
    app.add_handler(CommandHandler("chatid",         cmd_chatid))

    # Bot commands set karo (BotFather menu)
    await app.bot.set_my_commands([
        BotCommand("start",         "Home panel"),
        BotCommand("sessions",      "Saari loaded IDs"),
        BotCommand("joingroupall",  "Saare accounts group join"),
        BotCommand("leavegroupall", "Saare accounts group leave"),
        BotCommand("joinvcall",     "Saare accounts VC join"),
        BotCommand("leavevcall",    "Saare accounts VC leave"),
        BotCommand("addaccount",    "Naya account add karo"),
        BotCommand("loadall",       "Sessions folder reload"),
        BotCommand("chatid",        "Chat ID pao"),
        BotCommand("help",          "Commands list"),
    ])

    print("🤖 Bot chal raha hai...")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    return app


async def main():
    print("\n📱 Existing sessions load ho rahe hain...")
    loaded = await load_all_sessions()

    if loaded == 0:
        print("\n⚠️ Koi session nahi mila.")
        print("Pehla account add karne ke liye naam dalo:")
        sname = input("Session naam (e.g. acc1): ").strip()
        if sname:
            try:
                me = await add_new_session(sname)
                print(f"✅ {me.first_name} (ID: {me.id}) add ho gaya")
            except Exception as e:
                print(f"❌ {e}")
                return
    else:
        print(f"\n🟢 {loaded} accounts ready")

    # Bot + userbot sessions dono ek saath chalao
    app = await run_bot()

    print(f"\n✅ System ready!")
    print(f"   Loaded accounts : {len(clients)}")
    print(f"   Bot token       : {BOT_TOKEN[:10]}...")
    print(f"   Admin ID        : {ADMIN_ID}")
    print("   Ctrl+C se band karo\n")

    try:
        # Userbot sessions ko alive rakhne ke liye
        await asyncio.gather(*[c.run_until_disconnected() for c in clients])
    except (KeyboardInterrupt, SystemExit):
        print("\n⏹ Band ho raha hai...")
        await app.updater.stop()
        await app.stop()
        for c in clients:
            await c.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
