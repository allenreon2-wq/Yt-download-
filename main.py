import os
import asyncio
import json
import logging
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
main_loop = None # Fixed Async Loop tracking

# ==================== DATABASE FUNCTIONS ====================
def get_users():
    path = "data/users.json"
    if not os.path.exists(path):
        return {}
    with open(path, 'r') as f:
        return json.load(f)

def save_users(users):
    with open("data/users.json", 'w') as f:
        json.dump(users, f, indent=2)

def get_stats():
    path = "data/stats.json"
    if not os.path.exists(path):
        return {
            "total_downloads": 0, "youtube": 0, "tiktok": 0,
            "instagram": 0, "facebook": 0, "audio": 0
        }
    with open(path, 'r') as f:
        return json.load(f)

def save_stats(stats):
    with open("data/stats.json", 'w') as f:
        json.dump(stats, f, indent=2)

# ==================== PLATFORM DETECTION ====================
def detect_platform(url):
    url_lower = url.lower()
    if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return 'youtube'
    elif 'tiktok.com' in url_lower:
        return 'tiktok'
    elif 'instagram.com' in url_lower:
        return 'instagram'
    elif 'facebook.com' in url_lower or 'fb.watch' in url_lower:
        return 'facebook'
    elif 'twitter.com' in url_lower or 'x.com' in url_lower:
        return 'twitter'
    elif 'pinterest.com' in url_lower or 'pin.it' in url_lower:
        return 'pinterest'
    else:
        return None

# ==================== DOWNLOAD FUNCTION ====================
def download_media_sync(url, is_audio=False):
    try:
        ydl_opts = {
            'outtmpl': 'downloads/%(title)s_%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'socket_timeout': 60,
            'retries': 3,
            'extract_flat': False,
        }
        
        if is_audio:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            ydl_opts['format'] = 'best[height<=720]'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            downloaded_file = None
            for f in os.listdir("downloads"):
                if info['id'] in f:
                    downloaded_file = f"downloads/{f}"
                    break
            
            if downloaded_file:
                file_size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
                return {
                    'path': downloaded_file,
                    'title': info.get('title', 'Media')[:50],
                    'size_mb': round(file_size_mb, 1),
                    'duration': info.get('duration', 0),
                    'platform': info.get('extractor', 'unknown')
                }
        return None
    except Exception as e:
        logger.error(f"Download error: {e}")
        return None

# ==================== BOT HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    users = get_users()
    if str(user.id) not in users:
        users[str(user.id)] = {
            "username": user.username or "N/A",
            "first_name": user.first_name,
            "joined_date": str(datetime.now()),
            "downloads": 0
        }
        save_users(users)
    
    keyboard = [
        [InlineKeyboardButton("📺 YouTube", callback_data="info_youtube"),
         InlineKeyboardButton("🎵 TikTok", callback_data="info_tiktok")],
        [InlineKeyboardButton("📸 Instagram", callback_data="info_instagram"),
         InlineKeyboardButton("📘 Facebook", callback_data="info_facebook")],
        [InlineKeyboardButton("📊 Statistics", callback_data="stats"),
         InlineKeyboardButton("❓ Help", callback_data="help")],
        [InlineKeyboardButton("👑 Premium", callback_data="premium"),
         InlineKeyboardButton("ℹ️ About", callback_data="about")]
    ]
    
    welcome_text = f"🎉 **Welcome {user.first_name}!**\n\n⚡ **Media Downloader Bot v4.0**\n\n📥 **Send links from YT, TikTok, Insta, FB!**"
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = "📚 **How to Use Bot**\n\n1. Send link\n2. Choose format\n3. Get file!"
    await update.message.reply_text(help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="home")]]), parse_mode=ParseMode.MARKDOWN)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_stats()
    users = get_users()
    stats_text = f"📊 **Bot Statistics**\n\n👥 Users: {len(users)}\n📥 Total Downloads: {stats['total_downloads']}"
    await update.message.reply_text(stats_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="home")]]), parse_mode=ParseMode.MARKDOWN)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    platform = detect_platform(url)
    
    if platform:
        context.user_data['url'] = url
        context.user_data['platform'] = platform
        keyboard = [
            [InlineKeyboardButton("📥 Download Video", callback_data="dl_video"),
             InlineKeyboardButton("🎵 Download Audio", callback_data="dl_audio")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
        ]
        await update.message.reply_text(f"✅ **{platform.title()} Link Detected!**\n\nChoose option:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("❌ Invalid Link!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="home")]]))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    
    if data == "home":
        await query.message.delete()
        keyboard = [[InlineKeyboardButton("📊 Statistics", callback_data="stats"), InlineKeyboardButton("❓ Help", callback_data="help")]]
        await context.bot.send_message(chat_id=chat_id, text="🏠 **Main Menu**\n\nSend a link to download.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    elif data == "help":
        await query.message.edit_text("❓ Send video link, click download.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="home")]]))
    elif data == "stats":
        stats = get_stats()
        await query.message.edit_text(f"📊 Downloads: {stats['total_downloads']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="home")]]))
    elif data == "premium":
        await query.message.edit_text("👑 Premium details...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="home")]]))
    elif data == "about":
        await query.message.edit_text("ℹ️ About Bot Engine...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="home")]]))
    
    elif data in ["dl_video", "dl_audio"]:
        is_audio = data == "dl_audio"
        url = context.user_data.get('url')
        platform = context.user_data.get('platform', 'unknown')
        
        if not url:
            await query.message.edit_text("❌ Session expired!")
            return
        
        processing_msg = await query.message.edit_text("⏳ **Processing media... Please wait.**")
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, download_media_sync, url, is_audio)
        
        if result:
            stats = get_stats()
            stats['total_downloads'] += 1
            if platform in stats: stats[platform] += 1
            if is_audio: stats['audio'] += 1
            save_stats(stats)
            
            try:
                await processing_msg.edit_text("📤 **Uploading...**")
                with open(result['path'], 'rb') as media_file:
                    if is_audio:
                        await context.bot.send_audio(chat_id=chat_id, audio=media_file, title=result['title'], caption="✅ Done!")
                    else:
                        await context.bot.send_video(chat_id=chat_id, video=media_file, caption="✅ Done!", supports_streaming=True)
                os.remove(result['path'])
                await processing_msg.delete()
            except Exception as e:
                await processing_msg.edit_text(f"❌ Upload failed: {str(e)[:50]}")
        else:
            await processing_msg.edit_text("❌ Download Failed!")

    elif data.startswith("info_"):
        platform_name = data.replace("info_", "")
        await query.message.edit_text(f"ℹ️ Info about {platform_name} support.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="home")]]))

# ==================== FLASK WEBHOOK (FIXED ASYNC INTERACTION) ====================
@flask_app.route('/webhook', methods=['POST'])
def webhook():
    global application, main_loop
    if application is None or main_loop is None:
        return jsonify({"error": "Bot not ready"}), 503
    
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        
        # Safe cross-thread async update push
        asyncio.run_coroutine_threadsafe(application.process_update(update), main_loop)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@flask_app.route('/')
def home():
    return jsonify({"status": "running", "bot": "Media Downloader Bot"})

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

# ==================== MAIN FUNCTION ====================
async def main_async():
    global application, main_loop
    main_loop = asyncio.get_running_loop() # Target main loop captured
    
    request_timeout = HTTPXRequest(
        connect_timeout=60.0, read_timeout=60.0,
        write_timeout=60.0, pool_timeout=60.0
    )
    
    application = Application.builder()\
        .token(BOT_TOKEN)\
        .request(request_timeout)\
        .build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(filters.TEXT & ~filters.COMMAND, handle_message) # Fixed syntax
    application.add_handler(CallbackQueryHandler(button_handler))
    
    await application.initialize()
    await application.start()
    
    render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    webhook_url = f"https://{render_hostname}/webhook" if render_hostname else f"http://localhost:{PORT}/webhook"
    
    await application.bot.delete_webhook()
    await application.bot.set_webhook(webhook_url)
    logger.info(f"✅ Webhook active on: {webhook_url}")
    
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await application.stop()
        await application.shutdown()

def run_flask():
    flask_app.run(host='0.0.0.0', port=PORT, threaded=True) # Threaded True for concurrent webhooks

if __name__ == "__main__":
    import threading
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        print("\n⚠️ Bot stopped!")
