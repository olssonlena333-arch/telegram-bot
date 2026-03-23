from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
import time
import sqlite3

print("BOT VERSION: ADMIN TOP + HIDDEN POINTS + PERSISTENT DISK")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = 6129752426
GROUP_ID = -1002464136190

ACTIVE_DROP = {
    "code": None,
    "points": 0,
    "end_time": 0,
    "winner_id": None,
    "winner_name": None
}

# --- Database (persistent disk) ---
DB_PATH = "/data/fwp.db"

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        points INTEGER DEFAULT 0
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS claims (
        user_id INTEGER,
        code TEXT,
        UNIQUE(user_id, code)
    )
""")

# Säker migration – lägg till username-kolumn om den inte finns
try:
    cursor.execute("ALTER TABLE users ADD COLUMN username TEXT")
    conn.commit()
    print("USERNAME COLUMN ADDED")
except Exception:
    pass

conn.commit()

# --- Helpers ---

def get_display_name(user):
    if user.username:
        return f"@{user.username}"
    return user.first_name or f"User {user.id}"

def get_points(user_id):
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, points) VALUES (?, 0)",
        (user_id,)
    )
    cursor.execute(
        "SELECT points FROM users WHERE user_id = ?",
        (user_id,)
    )
    return cursor.fetchone()[0]

def update_username(user):
    name = get_display_name(user)
    cursor.execute(
        "INSERT INTO users (user_id, username, points) VALUES (?, ?, 0) "
        "ON CONFLICT(user_id) DO UPDATE SET username = excluded.username",
        (user.id, name)
    )
    conn.commit()

def add_points(user_id, amount):
    cursor.execute(
        "UPDATE users SET points = points + ? WHERE user_id = ?",
        (amount, user_id)
    )
    conn.commit()

def has_claimed(user_id, code):
    cursor.execute(
        "SELECT 1 FROM claims WHERE user_id = ? AND code = ?",
        (user_id, code)
    )
    return cursor.fetchone() is not None

def save_claim(user_id, code):
    cursor.execute(
        "INSERT INTO claims (user_id, code) VALUES (?, ?)",
        (user_id, code)
    )
    conn.commit()

# --- Commands ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    update_username(user)
    points = get_points(user.id)

    if points == 0:
        text = "Velkommen! Du er nu med i Fast Win Points 🚀"
    else:
        text = "Du er allerede tilmeldt Fast Win Points 🎯"

    await update.effective_chat.send_message(text)

async def points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    update_username(user)

    # Admin kan alltid se sina poäng
    if user.id == ADMIN_ID:
        pts = get_points(user.id)
        name = get_display_name(user)
        await update.message.reply_text(f"{name} har {pts} FWP point 🎯")
        return

    # Alla andra får detta meddelande tills vidare
    await update.message.reply_text(
        "⏳ Point-oversigten opdateres i øjeblikket.\n"
        "Dine point er gemt og vil snart være synlige igen! 🎯"
    )

async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    update_username(user)
    user_id = user.id

    if not context.args:
        await update.message.reply_text("Brug: /claim KODE")
        return

    if not ACTIVE_DROP.get("code"):
        await update.message.reply_text("Der er ingen aktiv Flash Drop lige nu ❌")
        return

    if time.time() > ACTIVE_DROP.get("end_time", 0):
        await update.message.reply_text("For sent ⏰ Denne Flash Drop er udløbet.")
        return

    code = context.args[0]
    if code != ACTIVE_DROP.get("code"):
        await update.message.reply_text("Forkert kode ❌")
        return

    if has_claimed(user_id, code):
        await update.message.reply_text("Du har allerede brugt denne kode ❌")
        return

    if ACTIVE_DROP.get("winner_id") is None:
        ACTIVE_DROP["winner_id"] = user_id
        ACTIVE_DROP["winner_name"] = get_display_name(user)

    save_claim(user_id, code)
    add_points(user_id, ACTIVE_DROP.get("points", 0))

    await update.message.reply_text(
        f"✅ Kode godkendt!\nDu har fået {ACTIVE_DROP.get('points', 0)} point 🎯"
    )

# --- Admin ---

async def admin_newdrop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Du har ikke adgang.")
        return

    if len(context.args) != 3:
        await update.message.reply_text("Brug: /admin_newdrop KODE POINT MINUTTER")
        return

    code = context.args[0]
    pts = int(context.args[1])
    minutes = int(context.args[2])

    ACTIVE_DROP["code"] = code
    ACTIVE_DROP["points"] = pts
    ACTIVE_DROP["end_time"] = time.time() + minutes * 60
    ACTIVE_DROP["winner_id"] = None
    ACTIVE_DROP["winner_name"] = None

    await update.message.reply_text(
        f"✅ Flash Drop oprettet!\n"
        f"Kode: {code}\n"
        f"Point: {pts}\n"
        f"Tid: {minutes} min"
    )

    try:
        await context.bot.send_message(
            chat_id=GROUP_ID,
            text=(
                "🚨 FLASH DROP!\n\n"
                f"Kode: {code}\n"
                f"🎯 {pts} point\n"
                f"⏰ Gælder i {minutes} minutter\n\n"
                f"Skriv:\n/claim {code}"
            )
        )
        print("POSTED FLASH DROP TO GROUP")
    except Exception as e:
        print("ERROR posting to group:", e)

async def top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Endast admin kan se /top
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "⏳ Topplisten opdateres i øjeblikket.\n"
            "Den vil snart være synlig igen! 🏆"
        )
        return

    cursor.execute(
        "SELECT user_id, username, points FROM users ORDER BY points DESC LIMIT 10"
    )
    rows = cursor.fetchall()

    if not rows:
        await update.message.reply_text("Der er ingen point endnu.")
        return

    text = "🏆 Top 10 – Fast Win Points\n\n"
    rank = 1
    for user_id, username, pts in rows:
        name = username if username else f"User {user_id}"
        text += f"{rank}️⃣ {name} – {pts} pt\n"
        rank += 1

    await update.message.reply_text(text)

async def admin_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Du har ikke adgang.")
        return

    cursor.execute("UPDATE users SET points = 0")
    cursor.execute("DELETE FROM claims")
    conn.commit()

    await update.message.reply_text(
        "🔄 Konkurrencen er nulstillet!\nAlle point er sat til 0. Ny måned starter nu 🚀"
    )

async def admin_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Du har ikke adgang.")
        return

    cursor.execute(
        "SELECT user_id, username, points FROM users ORDER BY points DESC LIMIT 1"
    )
    row = cursor.fetchone()

    if not row or row[2] == 0:
        await update.message.reply_text(
            "Der er ingen vinder endnu – ingen point er optjent."
        )
        return

    user_id, username, pts = row
    name = username if username else f"User {user_id}"

    await update.message.reply_text(
        f"🏆 Månedens vinder!\n\n"
        f"{name}\n"
        f"med {pts} FWP point 🎉"
    )

async def check_flash_drop(context: ContextTypes.DEFAULT_TYPE):
    if not ACTIVE_DROP.get("code"):
        return

    if time.time() <= ACTIVE_DROP.get("end_time", 0):
        return

    winner = ACTIVE_DROP.get("winner_name")
    pts = ACTIVE_DROP.get("points", 0)

    if winner:
        text = (
            "⏰ Flash Drop er slut!\n\n"
            f"🏆 Vinderen er {winner}\n"
            f"🎯 +{pts} point"
        )
    else:
        text = (
            "⏰ Flash Drop er slut!\n\n"
            "Ingen deltog denne gang 😢"
        )

    await context.bot.send_message(chat_id=GROUP_ID, text=text)

    ACTIVE_DROP.clear()
    ACTIVE_DROP.update({
        "code": None,
        "points": 0,
        "end_time": 0,
        "winner_id": None,
        "winner_name": None
    })

# --- App ---
app = ApplicationBuilder().token(TOKEN).build()

app.job_queue.run_repeating(check_flash_drop, interval=5, first=5)

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("points", points))
app.add_handler(CommandHandler("claim", claim))
app.add_handler(CommandHandler("admin_newdrop", admin_newdrop))
app.add_handler(CommandHandler("top", top))
app.add_handler(CommandHandler("admin_reset", admin_reset))
app.add_handler(CommandHandler("admin_winner", admin_winner))

app.run_polling()
