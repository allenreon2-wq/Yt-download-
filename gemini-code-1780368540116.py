import os
import asyncio
import json
import logging
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest

# ==================== CONFIGURATION ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8106042109:AAHaMFkdXkaH5EYrLKbQTCqSuoHH6ecM5zU")
OWNER_ID = int(os.getenv("OWNER_ID", "8679298308"))
PORT = int(os.getenv("PORT", 10000))

# Create necessary directories
os.makedirs("downloads", exist_ok=True)
os.makedirs("data", exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app for webhook
flask_app = Flask(__name__)

# Global variables
application = None
executor = ThreadPoolExecutor(max_workers=4)
main_loop = None

# ==================== DATABASE FUNCTIONS ====================
def get_users():
    path = "data/users.json"
    if not os.path.exists(path): return {}
    try:
        with open(path, 'r') as f: return json.load(f)
    except: return {}

def save_users(users):
    with open("data/users.json", 'w') as f: json.dump(users, f, indent=2)

def get_stats():
    path = "data/stats.json"
    if not os.path.exists(path):
        return {"total_downloads": 0, "youtube": 0, "tiktok": 0, "instagram": 0, "facebook": 0, "audio": 0}
    try:
        with open(path, 'r') as f: return json.load(f)
    except: return {"total_downloads": 0}

def save_stats(stats):
    with open("data/stats.json", 'w') as f: json.dump(stats, f, indent=2)

# ==================== PLATFORM DETECTION ====================
def detect_platform(url):
    url_lower = url.lower()
    if 'youtube' in url_lower or 'youtu.be' in url_lower: return 'youtube'
    if 'tiktok' in url_lower: return 'tiktok'
    if 'instagram' in url_lower: return 'instagram'
    if 'facebook' in url_lower or 'fb.watch' in url_lower: return 'facebook'
    if 'twitter' in url_lower or 'x.com' in url_lower: return 'twitter'
    if 'pinterest' in url_lower or 'pin.it' in url_lower: return 'pinterest'
    return None

# ==================== DOWNLOAD FUNCTION ====================
def download_media_sync(url, is_audio=False):
    try:
        ydl_opts = {
            'outtmpl': 'downloads/%(title)s_%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'socket_timeout': 60,
            'retries': 3,
        }
        if is_audio:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'}]
        else:
            ydl_opts['format'] = 'best[height<=720]'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            did = info.get('id')
            downloaded_file = None
            for f in os.listdir("downloads"):
                if did in f:
                    downloaded_file = f"downloads/{f}"
                    break
            if downloaded_file:
                return {'path': downloaded_file, 'title': info.get('title', 'Media')[:50], 'size_mb': round(os.path.getsize(downloaded_file)/(1024*1024), 1)}
        return None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None

# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    users = get_users()
    if str(user.id) not in users:
        users[str(user.id)] = {"username": user.username or "N/A", "joined": str(datetime.now()), "downloads": 0}
        save_users(users)
    
    keyboard = [[InlineKeyboardButton("📊 Stats", callback_data="stats"), InlineKeyboardButton("❓ Help", callback_data="help")]]
    await update.message.reply_text(f"🎉 **Welcome {user.first_name}!**\n\nSend me any media link to download.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    platform = detect_platform(url)
    if platform:
        context.user_data['url'] = url
        context.user_data['platform'] = platform
        keyboard = [[InlineKeyboardButton("🎥 Video", callback_data="dl_video"), InlineKeyboardButton("🎵 Audio", callback_data="dl_audio")]]
        await update.message.reply_text(f"✅ **{platform.title()} Detected!**\nChoose format:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Invalid Link!")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "stats":
        s = get_stats()
        await query.message.edit_text(f"📊 Total Downloads: {s['total_downloads']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="home")]]))
    elif query.data == "home":
        await query.message.edit_text("🏠 Send a link to start!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 Stats", callback_data="stats")]]))
    elif query.data in ["dl_video", "dl_audio"]:
        is_audio = query.data == "dl_audio"
        url = context.user_data.get('url')
        if not url: return
        p_msg = await query.message.edit_text("⏳ Processing...")
        res = await asyncio.get_running_loop().run_in_executor(executor, download_media_sync, url, is_audio)
        if res:
            try:
                await p_msg.edit_text("📤 Uploading...")
                with open(res['path'], 'rb') as f:
                    if is_audio: await context.bot.send_audio(chat_id=query.message.chat_id, audio=f, title=res['title'])
                    else: await context.bot.send_video(chat_id=query.message.chat_id, video=f, caption="✅ Done!", supports_streaming=True)
                os.remove(res['path'])
                await p_msg.delete()
                # Update Stats
                st = get_stats()
                st['total_downloads'] += 1
                save_stats(st)
            except Exception as e: await p_msg.edit_text(f"❌ Error: {str(e)[:50]}")
        else: await p_msg.edit_text("❌ Failed!")

# ==================== WEBHOOK & FLASK ====================
@flask_app.route('/webhook', methods=['POST'])
def webhook():
    if application and main_loop:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), main_loop)
    return jsonify({"status": "ok"}), 200

@flask_app.route('/')
def home(): return "Bot is Running!"

# ==================== MAIN ====================
async def main_async():
    global application, main_loop
    main_loop = asyncio.get_running_loop()
    
    # Improved request parameters for stability
    req = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0)
    
    # Use updater=None to avoid the 'Updater' AttributeError in some environments
    application = Application.builder().token(BOT_TOKEN).request(req).updater(None).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    await application.initialize()
    await application.start()
    
    host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if host:
        url = f"https://{host}/webhook"
        await application.bot.set_webhook(url)
        logger.info(f"Webhook set: {url}")

    try:
        while True: await asyncio.sleep(3600)
    finally:
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    threading.Thread(target=lambda: flask_app.run(host='0.0.0.0', port=PORT), daemon=True).start()
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit): pass