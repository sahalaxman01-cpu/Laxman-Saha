import asyncio
import sqlite3
import re
import uuid
import os
from decimal import Decimal
from urllib.parse import quote

import aiohttp
from aiohttp import web

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

# =========================================================
# YOUR SETTINGS
# =========================================================

BOT_TOKEN = "PASTE_BOT_TOKEN_HERE"

ADMIN_ID = 7407301486

CHANNEL_1_LINK = "https://t.me/bhai_join_korle"
CHANNEL_2_LINK = "https://t.me/Hyper_Aura"

# Leave blank for now if Cashfree is not configured.
CASHFREE_CLIENT_ID = ""
CASHFREE_CLIENT_SECRET = ""
CASHFREE_PAYOUT_URL = ""

REFERRAL_REWARD = Decimal("2.00")
WITHDRAW_AMOUNTS = [10, 50, 80, 100]

# =========================================================
# BOT
# =========================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(
    "bot.db",
    check_same_thread=False
)

db.row_factory = sqlite3.Row

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    balance TEXT DEFAULT '0.00',
    referred_by INTEGER,
    referral_rewarded INTEGER DEFAULT 0,
    verified INTEGER DEFAULT 0
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount TEXT,
    transaction_id TEXT UNIQUE,
    status TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

db.commit()

user_states = {}

# =========================================================
# CHANNEL FUNCTIONS
# =========================================================

def channel_username(link):
    link = link.strip().rstrip("/")

    if link.startswith("@"):
        return link

    match = re.search(
        r"(?:https?://)?t\.me/([A-Za-z0-9_]+)",
        link
    )

    if match:
        return f"@{match.group(1)}"

    return None


CHANNEL_1 = channel_username(CHANNEL_1_LINK)
CHANNEL_2 = channel_username(CHANNEL_2_LINK)


async def is_member(user_id):
    if not CHANNEL_1 or not CHANNEL_2:
        return False

    try:
        member1 = await bot.get_chat_member(
            chat_id=CHANNEL_1,
            user_id=user_id
        )

        member2 = await bot.get_chat_member(
            chat_id=CHANNEL_2,
            user_id=user_id
        )

        allowed = {
            "member",
            "administrator",
            "creator",
            "owner"
        }

        status1 = str(member1.status).lower()
        status2 = str(member2.status).lower()

        return (
            status1 in allowed
            and status2 in allowed
        )

    except Exception as error:
        print(
            "Membership check error:",
            error
        )
        return False


# =========================================================
# DATABASE FUNCTIONS
# =========================================================

def get_user(user_id):
    return db.execute(
        """
        SELECT *
        FROM users
        WHERE user_id = ?
        """,
        (user_id,)
    ).fetchone()


def create_or_update_user(
    tg_user,
    referrer=None
):
    user = get_user(tg_user.id)

    if user is None:

        valid_referrer = None

        if referrer:
            if referrer != tg_user.id:
                if get_user(referrer):
                    valid_referrer = referrer

        db.execute(
            """
            INSERT INTO users (
                user_id,
                username,
                first_name,
                balance,
                referred_by
            )
            VALUES (?, ?, ?, '0.00', ?)
            """,
            (
                tg_user.id,
                tg_user.username,
                tg_user.first_name,
                valid_referrer
            )
        )

    else:

        db.execute(
            """
            UPDATE users
            SET username = ?,
                first_name = ?
            WHERE user_id = ?
            """,
            (
                tg_user.username,
                tg_user.first_name,
                tg_user.id
            )
        )

    db.commit()


# =========================================================
# KEYBOARDS
# =========================================================

def join_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📢 JOIN CHANNEL 1",
                    url=CHANNEL_1_LINK
                )
            ],
            [
                InlineKeyboardButton(
                    text="📢 JOIN CHANNEL 2",
                    url=CHANNEL_2_LINK
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ I JOINED / VERIFY",
                    callback_data="verify_join"
                )
            ]
        ]
    )


def main_menu():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 MY ACCOUNT 📋",
                    callback_data="account"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎁 REFER & EARN ♻️",
                    callback_data="refer"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🚀 WITHDRAWAL",
                    callback_data="withdraw"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Back",
                    callback_data="back"
                )
            ]
        ]
    )


def withdrawal_keyboard():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="₹10",
                    callback_data="amount_10"
                ),
                InlineKeyboardButton(
                    text="₹50",
                    callback_data="amount_50"
                )
            ],
            [
                InlineKeyboardButton(
                    text="₹80",
                    callback_data="amount_80"
                ),
                InlineKeyboardButton(
                    text="₹100",
                    callback_data="amount_100"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Back",
                    callback_data="back"
                )
            ]
        ]
    )


# =========================================================
# COMMON PAGES
# =========================================================

async def show_join(message):

    await message.answer(
        "⚠️ <b>YOU MUST JOIN BOTH CHANNELS FIRST!</b>\n\n"
        "Please join both channels below.\n"
        "After joining, click:\n\n"
        "✅ <b>I JOINED / VERIFY</b>",
        reply_markup=join_keyboard(),
        parse_mode="HTML"
    )


async def show_home(message):

    await message.answer(
        "🎉 <b>WELCOME!</b>\n\n"
        "Choose an option below:",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


async def guard_message(message):

    if not await is_member(
        message.from_user.id
    ):
        await show_join(message)
        return False

    return True


async def guard_callback(callback):

    if not await is_member(
        callback.from_user.id
    ):

        await callback.answer(
            "Please join both channels first.",
            show_alert=True
        )

        await show_join(
            callback.message
        )

        return False

    return True


# =========================================================
# REFERRAL REWARD
# =========================================================

async def reward_referrer(
    new_user_id
):

    user = get_user(
        new_user_id
    )

    if user is None:
        return

    if user["referral_rewarded"] == 1:
        return

    referrer_id = user["referred_by"]

    if not referrer_id:
        return

    referrer = get_user(
        referrer_id
    )

    if referrer is None:
        return

    try:

        db.execute(
            "BEGIN IMMEDIATE"
        )

        latest_user = db.execute(
            """
            SELECT referral_rewarded
            FROM users
            WHERE user_id = ?
            """,
            (new_user_id,)
        ).fetchone()

        if (
            latest_user["referral_rewarded"]
            == 1
        ):
            db.rollback()
            return

        latest_referrer = db.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id = ?
            """,
            (referrer_id,)
        ).fetchone()

        old_balance = Decimal(
            latest_referrer["balance"]
        )

        new_balance = (
            old_balance
            + REFERRAL_REWARD
        )

        db.execute(
            """
            UPDATE users
            SET balance = ?
            WHERE user_id = ?
            """,
            (
                str(new_balance),
                referrer_id
            )
        )

        db.execute(
            """
            UPDATE users
            SET referral_rewarded = 1
            WHERE user_id = ?
            """,
            (new_user_id,)
        )

        db.commit()

    except Exception as error:

        db.rollback()

        print(
            "Referral reward error:",
            error
        )

        return

    friend = get_user(
        new_user_id
    )

    if friend["username"]:

        friend_display = (
            f'<a href="https://t.me/'
            f'{friend["username"]}">'
            f'@{friend["username"]}'
            f'</a>'
        )

    else:

        friend_name = (
            friend["first_name"]
            or "Telegram User"
        )

        friend_display = (
            f'<a href="tg://user?id='
            f'{new_user_id}">'
            f'{friend_name}'
            f'</a>'
        )

    try:

        await bot.send_message(
            chat_id=referrer_id,
            text=(
                "🎉 <b>CONGRATULATIONS!</b>\n\n"
                f"👤 Your friend {friend_display} "
                "successfully joined and verified.\n\n"
                "💰 ₹2.00 has been credited "
                "to your wallet.\n"
                f"💳 Current Balance: "
                f"₹{new_balance:.2f}"
            ),
            parse_mode="HTML"
        )

    except Exception as error:

        print(
            "Referral notification error:",
            error
        )


# =========================================================
# START
# =========================================================

@dp.message(CommandStart())
async def start_handler(
    message: Message
):

    args = message.text.split(
        maxsplit=1
    )

    referrer = None

    if len(args) > 1:

        try:
            referrer = int(
                args[1]
            )

        except ValueError:
            referrer = None

    create_or_update_user(
        message.from_user,
        referrer
    )

    if not await is_member(
        message.from_user.id
    ):

        await show_join(message)
        return

    db.execute(
        """
        UPDATE users
        SET verified = 1
        WHERE user_id = ?
        """,
        (message.from_user.id,)
    )

    db.commit()

    await reward_referrer(
        message.from_user.id
    )

    await show_home(message)


# =========================================================
# VERIFY JOIN
# =========================================================

@dp.callback_query(
    F.data == "verify_join"
)
async def verify_join(
    callback: CallbackQuery
):

    create_or_update_user(
        callback.from_user
    )

    await callback.answer(
        "Checking membership..."
    )

    if not await is_member(
        callback.from_user.id
    ):

        await callback.message.answer(
            "❌ <b>VERIFICATION FAILED!</b>\n\n"
            "You have not joined both channels yet.\n\n"
            "Please join both channels and try again.",
            reply_markup=join_keyboard(),
            parse_mode="HTML"
        )

        return

    db.execute(
        """
        UPDATE users
        SET verified = 1
        WHERE user_id = ?
        """,
        (callback.from_user.id,)
    )

    db.commit()

    await reward_referrer(
        callback.from_user.id
    )

    await callback.message.answer(
        "✅ <b>VERIFICATION SUCCESSFUL!</b>\n\n"
        "You can now use the bot.",
        parse_mode="HTML"
    )

    await show_home(
        callback.message
    )


# =========================================================
# MY ACCOUNT
# =========================================================

async def account_page(
    message,
    user_id
):

    user = get_user(
        user_id
    )

    total_referrals = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM users
        WHERE referred_by = ?
        AND referral_rewarded = 1
        """,
        (user_id,)
    ).fetchone()["total"]

    if user["username"]:
        username = (
            f'@{user["username"]}'
        )
    else:
        username = "Not Set"

    balance = Decimal(
        user["balance"]
    )

    await message.answer(
        "👤 <b>MY ACCOUNT 📋</b>\n\n"
        f"💰 Wallet Balance: "
        f"₹{balance:.2f}\n"
        f"👥 Successful Referrals: "
        f"{total_referrals}\n"
        f"🔹 Username: {username}\n"
        f"🆔 Telegram ID: "
        f"<code>{user_id}</code>",
        reply_markup=main_menu(),
        parse_mode="HTML"
    )


@dp.callback_query(
    F.data == "account"
)
async def account_callback(
    callback: CallbackQuery
):

    if not await guard_callback(
        callback
    ):
        return

    await callback.answer()

    await account_page(
        callback.message,
        callback.from_user.id
    )


@dp.message(
    Command("acc")
)
async def account_command(
    message: Message
):

    create_or_update_user(
        message.from_user
    )

    if not await guard_message(
        message
    ):
        return

    await account_page(
        message,
        message.from_user.id
    )


# =========================================================
# REFER & EARN
# =========================================================

async def referral_page(
    message,
    user_id
):

    bot_info = await bot.get_me()

    referral_link = (
        f"https://t.me/"
        f"{bot_info.username}"
        f"?start={user_id}"
    )

    share_text = (
        "Join this bot and start earning!"
    )

    share_url = (
        "https://t.me/share/url"
        f"?url={quote(referral_link)}"
        f"&text={quote(share_text)}"
    )

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 SHARE WITH FRIENDS",
                    url=share_url
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Back",
                    callback_data="back"
                )
            ]
        ]
    )

    await message.answer(
        "🎁 <b>REFER & EARN ♻️</b>\n\n"
        "💰 Earn ₹2 for every "
        "successful referral!\n\n"
        "Your friend must:\n\n"
        "1️⃣ Start the bot using "
        "your referral link\n"
        "2️⃣ Join both required channels\n"
        "3️⃣ Click I JOINED / VERIFY\n\n"
        "After successful verification, "
        "₹2 will be credited "
        "to your wallet.\n\n"
        "🔗 <b>Your Referral Link:</b>\n"
        f"<code>{referral_link}</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


@dp.callback_query(
    F.data == "refer"
)
async def refer_callback(
    callback: CallbackQuery
):

    if not await guard_callback(
        callback
    ):
        return

    await callback.answer()

    await referral_page(
        callback.message,
        callback.from_user.id
    )


@dp.message(
    Command("ref")
)
async def refer_command(
    message: Message
):

    create_or_update_user(
        message.from_user
    )

    if not await guard_message(
        message
    ):
        return

    await referral_page(
        message,
        message.from_user.id
    )


# =========================================================
# WITHDRAWAL MENU
# =========================================================

async def show_withdrawal_menu(
    message,
    user_id
):

    user = get_user(
        user_id
    )

    balance = Decimal(
        user["balance"]
    )

    await message.answer(
        "🚀 <b>WITHDRAWAL</b>\n\n"
        f"💰 Available Balance: "
        f"₹{balance:.2f}\n\n"
        "Select withdrawal amount:",
        reply_markup=withdrawal_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(
    F.data == "withdraw"
)
async def withdrawal_callback(
    callback: CallbackQuery
):

    if not await guard_callback(
        callback
    ):
        return

    await callback.answer()

    await show_withdrawal_menu(
        callback.message,
        callback.from_user.id
    )


@dp.message(
    Command("wit")
)
async def withdrawal_command(
    message: Message
):

    create_or_update_user(
        message.from_user
    )

    if not await guard_message(
        message
    ):
        return

    await show_withdrawal_menu(
        message,
        message.from_user.id
    )


# =========================================================
# SELECT WITHDRAWAL AMOUNT
# =========================================================

@dp.callback_query(
    F.data.startswith("amount_")
)
async def select_amount(
    callback: CallbackQuery
):

    if not await guard_callback(
        callback
    ):
        return

    try:

        amount = int(
            callback.data.split(
                "_"
            )[1]
        )

    except Exception:

        await callback.answer(
            "Invalid amount.",
            show_alert=True
        )

        return

    if amount not in WITHDRAW_AMOUNTS:

        await callback.answer(
            "Invalid amount.",
            show_alert=True
        )

        return

    user = get_user(
        callback.from_user.id
    )

    balance = Decimal(
        user["balance"]
    )

    if balance < Decimal(
        str(amount)
    ):

        await callback.answer(
            "❌ Insufficient Fund",
            show_alert=True
        )

        return

    user_states[
        callback.from_user.id
    ] = {
        "state": "waiting_upi",
        "amount": amount
    }

    await callback.answer()

    await callback.message.answer(
        f"💳 <b>Withdrawal Amount: "
        f"₹{amount}</b>\n\n"
        "Please send your UPI ID.\n\n"
        "Example: <code>name@upi</code>\n\n"
        "⚠️ Your UPI ID is requested "
        "for this withdrawal only.",
        parse_mode="HTML"
    )


# =========================================================
# UPI VALIDATION
# =========================================================

def valid_upi(
    upi_id
):

    pattern = (
        r"^[a-zA-Z0-9.\-_]{2,256}"
        r"@[a-zA-Z0-9.\-_]{2,64}$"
    )

    return bool(
        re.match(
            pattern,
            upi_id
        )
    )


# =========================================================
# CASHFREE PAYOUT
# =========================================================

async def cashfree_payout(
    upi_id,
    amount,
    transaction_id
):

    # Cashfree is not configured yet
    if (
        not CASHFREE_CLIENT_ID
        or not CASHFREE_CLIENT_SECRET
        or not CASHFREE_PAYOUT_URL
    ):

        return {
            "success": False,
            "status": "CONFIGURATION_ERROR"
        }

    headers = {
        "Content-Type":
            "application/json",

        "x-client-id":
            CASHFREE_CLIENT_ID,

        "x-client-secret":
            CASHFREE_CLIENT_SECRET
    }

    payload = {
        "transfer_id":
            transaction_id,

        "transfer_amount":
            float(amount),

        "transfer_mode":
            "upi",

        "beneficiary_details": {
            "vpa": upi_id
        }
    }

    try:

        timeout = (
            aiohttp.ClientTimeout(
                total=30
            )
        )

        async with (
            aiohttp.ClientSession(
                timeout=timeout
            )
        ) as session:

            async with session.post(
                CASHFREE_PAYOUT_URL,
                json=payload,
                headers=headers
            ) as response:

                data = (
                    await response.json(
                        content_type=None
                    )
                )

                print(
                    "Cashfree response:",
                    data
                )

                status = str(
                    data.get("status")
                    or data.get(
                        "transfer_status"
                    )
                    or ""
                ).upper()

                if status in {
                    "SUCCESS",
                    "SUCCESSFUL",
                    "COMPLETED"
                }:

                    return {
                        "success": True,
                        "status": status,
                        "data": data
                    }

                if status in {
                    "PENDING",
                    "PROCESSING",
                    "RECEIVED"
                }:

                    return {
                        "success": None,
                        "status": status,
                        "data": data
                    }

                return {
                    "success": False,
                    "status":
                        status or "FAILED",
                    "data": data
                }

    except Exception as error:

        print(
            "Cashfree API error:",
            error
        )

        return {
            "success": False,
            "status": "API_ERROR"
        }


# =========================================================
# RECEIVE UPI ID
# =========================================================

@dp.message(F.text)
async def text_handler(
    message: Message
):

    user_id = (
        message.from_user.id
    )

    create_or_update_user(
        message.from_user
    )

    state = user_states.get(
        user_id
    )

    if state is None:
        return

    if (
        state.get("state")
        != "waiting_upi"
    ):
        return

    if not await guard_message(
        message
    ):

        user_states.pop(
            user_id,
            None
        )

        return

    upi_id = (
        message.text.strip()
    )

    amount = Decimal(
        str(
            state["amount"]
        )
    )

    if not valid_upi(
        upi_id
    ):

        await message.answer(
            "❌ <b>INVALID UPI ID</b>\n\n"
            "Please enter a valid "
            "UPI ID.\n\n"
            "Example: "
            "<code>name@upi</code>",
            parse_mode="HTML"
        )

        return

    user_states.pop(
        user_id,
        None
    )

    transaction_id = (
        f"WD_{user_id}_"
        f"{uuid.uuid4().hex[:12].upper()}"
    )

    try:

        db.execute(
            "BEGIN IMMEDIATE"
        )

        user = db.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        balance = Decimal(
            user["balance"]
        )

        if balance < amount:

            db.rollback()

            await message.answer(
                "❌ <b>INSUFFICIENT FUND</b>",
                parse_mode="HTML"
            )

            return

        new_balance = (
            balance - amount
        )

        db.execute(
            """
            UPDATE users
            SET balance = ?
            WHERE user_id = ?
            """,
            (
                str(new_balance),
                user_id
            )
        )

        db.execute(
            """
            INSERT INTO withdrawals (
                user_id,
                amount,
                transaction_id,
                status
            )
            VALUES (?, ?, ?, 'PROCESSING')
            """,
            (
                user_id,
                str(amount),
                transaction_id
            )
        )

        db.commit()

    except Exception as error:

        db.rollback()

        print(
            "Withdrawal database error:",
            error
        )

        await message.answer(
            "❌ Withdrawal could not "
            "be started. Please try again."
        )

        return

    processing_message = (
        await message.answer(
            "⏳ <b>PROCESSING YOUR "
            "WITHDRAWAL...</b>",
            parse_mode="HTML"
        )
    )

    result = await cashfree_payout(
        upi_id,
        amount,
        transaction_id
    )

    # SUCCESS
    if result["success"] is True:

        db.execute(
            """
            UPDATE withdrawals
            SET status = 'SUCCESS'
            WHERE transaction_id = ?
            """,
            (transaction_id,)
        )

        db.commit()

        await processing_message.edit_text(
            "✅ <b>WITHDRAWAL SUCCESSFUL!</b>\n\n"
            f"💰 Amount: ₹{amount:.2f}\n"
            f"💳 UPI ID: "
            f"<code>{upi_id}</code>\n\n"
            "🧾 Transaction ID:\n"
            f"<code>{transaction_id}</code>",
            parse_mode="HTML"
        )

    # PENDING
    elif result["success"] is None:

        db.execute(
            """
            UPDATE withdrawals
            SET status = 'PENDING'
            WHERE transaction_id = ?
            """,
            (transaction_id,)
        )

        db.commit()

        await processing_message.edit_text(
            "⏳ <b>WITHDRAWAL PROCESSING</b>\n\n"
            f"💰 Amount: ₹{amount:.2f}\n\n"
            "🧾 Transaction ID:\n"
            f"<code>{transaction_id}</code>\n\n"
            "Your transaction is being processed.",
            parse_mode="HTML"
        )

    # FAILED
    else:

        try:

            db.execute(
                "BEGIN IMMEDIATE"
            )

            user = db.execute(
                """
                SELECT balance
                FROM users
                WHERE user_id = ?
                """,
                (user_id,)
            ).fetchone()

            refunded_balance = (
                Decimal(
                    user["balance"]
                )
                + amount
            )

            db.execute(
                """
                UPDATE users
                SET balance = ?
                WHERE user_id = ?
                """,
                (
                    str(
                        refunded_balance
                    ),
                    user_id
                )
            )

            db.execute(
                """
                UPDATE withdrawals
                SET status = 'FAILED'
                WHERE transaction_id = ?
                """,
                (transaction_id,)
            )

            db.commit()

        except Exception as error:

            db.rollback()

            print(
                "Refund error:",
                error
            )

        await processing_message.edit_text(
            "❌ <b>WITHDRAWAL FAILED</b>\n\n"
            "The withdrawal could not "
            "be completed.\n"
            "Your wallet balance "
            "has been restored.\n\n"
            "🧾 Transaction ID:\n"
            f"<code>{transaction_id}</code>",
            parse_mode="HTML"
        )


# =========================================================
# BACK
# =========================================================

@dp.callback_query(
    F.data == "back"
)
async def back_callback(
    callback: CallbackQuery
):

    if not await guard_callback(
        callback
    ):
        return

    user_states.pop(
        callback.from_user.id,
        None
    )

    await callback.answer()

    await show_home(
        callback.message
    )


@dp.message(
    Command("back")
)
async def back_command(
    message: Message
):

    create_or_update_user(
        message.from_user
    )

    user_states.pop(
        message.from_user.id,
        None
    )

    if not await guard_message(
        message
    ):
        return

    await show_home(
        message
    )


# =========================================================
# RENDER FREE WEB SERVER
# =========================================================

async def health(
    request
):

    return web.Response(
        text="Telegram Bot is Running!"
    )


async def start_web_server():

    app = web.Application()

    app.router.add_get(
        "/",
        health
    )

    app.router.add_get(
        "/health",
        health
    )

    runner = web.AppRunner(
        app
    )

    await runner.setup()

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        port
    )

    await site.start()

    print(
        f"Web server running "
        f"on port {port}"
    )


# =========================================================
# RUN BOT + WEB SERVER
# =========================================================

async def main():

    print(
        "Starting Telegram Bot..."
    )

    await start_web_server()

    print(
        "Bot is running..."
    )

    await dp.start_polling(
        bot,
        allowed_updates=
            dp.resolve_used_update_types()
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )
