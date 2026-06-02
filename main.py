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

# ==================== DATABASE FUNCTIONS ====================
def get_users():
    """Load users from JSON file"""
    path = "data/users.json"
    if not os.path.exists(path):
        return {}
    with open(path, 'r') as f:
        return json.load(f)

def save_users(users):
    """Save users to JSON file"""
    with open("data/users.json", 'w') as f:
        json.dump(users, f, indent=2)

def get_stats():
    """Load statistics"""
    path = "data/stats.json"
    if not os.path.exists(path):
        return {
            "total_downloads": 0,
            "youtube": 0,
            "tiktok": 0,
            "instagram": 0,
            "facebook": 0,
            "audio": 0
        }
    with open(path, 'r') as f:
        return json.load(f)

def save_stats(stats):
    """Save statistics"""
    with open("data/stats.json", 'w') as f:
        json.dump(stats, f, indent=2)

# ==================== PLATFORM DETECTION ====================
def detect_platform(url):
    """Detect platform from URL"""
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
    """Synchronous download function - runs in thread pool"""
    try:
        # Configure yt-dlp options
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
            # Default to best quality with 720p limit for faster downloads
            ydl_opts['format'] = 'best[height<=720]'
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # Find the downloaded file
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
    """Handle /start command"""
    user = update.effective_user
    
    # Save user to database
    users = get_users()
    if str(user.id) not in users:
        users[str(user.id)] = {
            "username": user.username or "N/A",
            "first_name": user.first_name,
            "joined_date": str(datetime.now()),
            "downloads": 0
        }
        save_users(users)
    
    # Create main menu keyboard
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
    
    welcome_text = f"""
🎉 **Welcome {user.first_name}!**

⚡ **Media Downloader Bot v4.0**

📥 **Send me any media link from:**
• YouTube
• TikTok
• Instagram
• Facebook
• Twitter/X
• Pinterest

💎 **Features:**
• No watermark
• Audio extraction (MP3)
• Fast downloads
• Multiple quality options

**Status:** {'👑 Premium User' if user.id == OWNER_ID else '✅ Free User'}

Just send me a link to get started!
    """
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle help command"""
    help_text = """
📚 **How to Use Media Downloader Bot**

**Step 1:** Send me any video/audio link
**Step 2:** Choose your preferred format
**Step 3:** Get your file instantly!

**Supported Platforms:**
✅ YouTube - Videos, Shorts, Playlists
✅ TikTok - Videos, Photos, Slideshows
✅ Instagram - Reels, Posts, Stories
✅ Facebook - Videos, Reels
✅ Twitter/X - Videos, GIFs
✅ Pinterest - Pins, Videos

**Commands:**
/start - Restart the bot
/help - Show this help
/stats - Bot statistics

**Premium Features:**
• HD/4K quality
• Batch downloads
• Priority processing
• No ads

**Need help?** Contact @YourUsername
    """
    
    keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="home")]]
    await update.message.reply_text(
        help_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle stats command"""
    stats = get_stats()
    users = get_users()
    
    stats_text = f"""
📊 **Bot Statistics**

👥 **Total Users:** {len(users)}
📥 **Total Downloads:** {stats['total_downloads']}

**Platform Breakdown:**
📺 YouTube: {stats.get('youtube', 0)}
🎵 TikTok: {stats.get('tiktok', 0)}
📸 Instagram: {stats.get('instagram', 0)}
📘 Facebook: {stats.get('facebook', 0)}
🎧 Audio Extracts: {stats.get('audio', 0)}

📈 **Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
    """
    
    keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="home")]]
    await update.message.reply_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    url = update.message.text.strip()
    user_id = update.effective_user.id
    
    # Detect platform
    platform = detect_platform(url)
    
    if platform:
        # Store URL in user data
        context.user_data['url'] = url
        context.user_data['platform'] = platform
        
        # Create download options keyboard
        keyboard = [
            [InlineKeyboardButton("📥 Download Video", callback_data="dl_video"),
             InlineKeyboardButton("🎵 Download Audio", callback_data="dl_audio")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="home")]
        ]
        
        # Platform-specific info
        platform_emojis = {
            'youtube': '📺', 'tiktok': '🎵', 'instagram': '📸',
            'facebook': '📘', 'twitter': '🐦', 'pinterest': '📌'
        }
        emoji = platform_emojis.get(platform, '🔗')
        
        await update.message.reply_text(
            f"{emoji} **{platform.title()} Link Detected!**\n\n"
            f"🔗 `{url[:60]}...`\n\n"
            f"**Choose your download option:**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Invalid link
        keyboard = [[InlineKeyboardButton("🏠 Main Menu", callback_data="home")]]
        await update.message.reply_text(
            "❌ **Invalid Link!**\n\n"
            "Please send a valid link from:\n"
            "• YouTube\n• TikTok\n• Instagram\n• Facebook\n• Twitter/X\n• Pinterest\n\n"
            "Send /help for more information.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    
    # ========== NAVIGATION ==========
    if data == "home":
        await query.message.delete()
        # Create a new start message
        user = query.from_user
        keyboard = [
            [InlineKeyboardButton("📊 Statistics", callback_data="stats"),
             InlineKeyboardButton("❓ Help", callback_data="help")],
            [InlineKeyboardButton("👑 Premium", callback_data="premium"),
             InlineKeyboardButton("ℹ️ About", callback_data="about")]
        ]
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🏠 **Main Menu**\n\nWelcome back {user.first_name}! Send me a link to download.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "help":
        help_text = """
❓ **Help & Support**

**Quick Guide:**
1. Send a media link
2. Choose Video or Audio
3. Get your file!

**Example links:**
• `https://youtube.com/watch?v=...`
• `https://tiktok.com/@user/video/...`
• `https://instagram.com/p/...`

**Problems?**
• Make sure link is public
• Check if content is available
• Try again after some time

**Support:** @YourUsername
        """
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="home")]]
        await query.message.edit_text(
            help_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "stats":
        stats = get_stats()
        users = get_users()
        
        stats_text = f"""
📊 **Bot Statistics**

👥 **Users:** {len(users)}
📥 **Downloads:** {stats['total_downloads']}

📺 YouTube: {stats.get('youtube', 0)}
🎵 TikTok: {stats.get('tiktok', 0)}
📸 Instagram: {stats.get('instagram', 0)}
📘 Facebook: {stats.get('facebook', 0)}
🎧 Audio: {stats.get('audio', 0)}
        """
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="home")]]
        await query.message.edit_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "premium":
        premium_text = """
👑 **Premium Features**

**Free Tier:**
• SD quality (480p)
• Single downloads
• Standard speed

**Premium Tier ($5/month):**
• HD/4K quality
• Audio extraction (MP3)
• Batch downloads
• Priority processing
• No ads
• 24/7 support

**How to upgrade:**
Contact @YourUsername to get premium access!

💳 **Payment:** USDT, BTC, PayPal
        """
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="home")]]
        await query.message.edit_text(
            premium_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "about":
        about_text = """
ℹ️ **About Media Downloader Bot**

**Version:** 4.0
**Engine:** yt-dlp
**Framework:** python-telegram-bot

**Features:**
• Multi-platform support
• No watermark
• Audio extraction
• Fast downloads

**Developer:** @YourUsername
**Source:** Private Repository

**Uptime:** 99.9%
**Support:** 24/7 Available
        """
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="home")]]
        await query.message.edit_text(
            about_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
    
    # ========== DOWNLOAD HANDLERS ==========
    elif data in ["dl_video", "dl_audio"]:
        is_audio = data == "dl_audio"
        url = context.user_data.get('url')
        platform = context.user_data.get('platform', 'unknown')
        
        if not url:
            await query.message.edit_text("❌ Session expired! Please send the link again.")
            return
        
        # Update user download count
        users = get_users()
        if str(user_id) in users:
            users[str(user_id)]['downloads'] = users[str(user_id)].get('downloads', 0) + 1
            save_users(users)
        
        # Send processing message
        processing_msg = await query.message.edit_text(
            f"⏳ **Processing {'Audio' if is_audio else 'Video'}...**\n\n"
            f"📱 Platform: {platform.title()}\n"
            f"🔗 Fetching media...\n\n"
            f"⏱️ Please wait, this may take a moment."
        )
        
        # Run download in thread pool
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(executor, download_media_sync, url, is_audio)
        
        if result:
            # Update statistics
            stats = get_stats()
            stats['total_downloads'] += 1
            if platform in stats:
                stats[platform] += 1
            if is_audio:
                stats['audio'] += 1
            save_stats(stats)
            
            try:
                # Update progress
                await processing_msg.edit_text(f"📤 **Uploading to Telegram...**\n\n📏 Size: {result['size_mb']}MB")
                
                # Send the file
                with open(result['path'], 'rb') as media_file:
                    if is_audio:
                        await context.bot.send_audio(
                            chat_id=chat_id,
                            audio=media_file,
                            title=result['title'],
                            performer=platform.title(),
                            caption=f"✅ **Download Complete!**\n\n"
                                   f"📱 Platform: {platform.title()}\n"
                                   f"📏 Size: {result['size_mb']}MB\n"
                                   f"🎵 Format: MP3\n\n"
                                   f"⚡ Downloaded by @{context.bot.username}",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    else:
                        await context.bot.send_video(
                            chat_id=chat_id,
                            video=media_file,
                            caption=f"✅ **Download Complete!**\n\n"
                                   f"📱 Platform: {platform.title()}\n"
                                   f"📏 Size: {result['size_mb']}MB\n\n"
                                   f"⚡ Downloaded by @{context.bot.username}",
                            parse_mode=ParseMode.MARKDOWN,
                            supports_streaming=True
                        )
                
                # Clean up
                os.remove(result['path'])
                await processing_msg.delete()
                
                # Send completion message
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="💎 **Ready for more!** Send another link to continue.\n\n"
                         "Or use /start for main menu.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="home")]])
                )
                
            except Exception as e:
                logger.error(f"Upload error: {e}")
                await processing_msg.edit_text(
                    f"❌ **Upload Failed!**\n\n"
                    f"Error: {str(e)[:100]}\n\n"
                    f"Please try again or contact support."
                )
        else:
            await processing_msg.edit_text(
                "❌ **Download Failed!**\n\n"
                "Possible reasons:\n"
                "• Invalid or private link\n"
                "• Content not available in your region\n"
                "• Server temporarily down\n\n"
                "Please check the link and try again.\n\n"
                "If problem persists, contact @YourUsername"
            )
    
    # ========== INFO HANDLERS ==========
    elif data.startswith("info_"):
        platform_name = data.replace("info_", "")
        info_texts = {
            "youtube": "📺 **YouTube Support**\n\n• Videos (any quality)\n• Shorts\n• Playlists (Premium)\n• Audio extraction\n• No watermark",
            "tiktok": "🎵 **TikTok Support**\n\n• Videos without watermark\n• Photo slideshows\n• Audio extraction\n• Profile videos",
            "instagram": "📸 **Instagram Support**\n\n• Reels\n• Posts\n• Stories (Premium)\n• IGTV videos\n• No watermark",
            "facebook": "📘 **Facebook Support**\n\n• Public videos\n• Reels\n• Watch videos\n• HD quality available"
        }
        info_text = info_texts.get(platform_name, f"**{platform_name.title()} Support**\n\nSend any public link and I'll download it for you!")
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="home")]]
        await query.message.edit_text(
            info_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )

# ==================== FLASK WEBHOOK ====================
@flask_app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook requests from Telegram"""
    global application
    if application is None:
        return jsonify({"error": "Bot not ready"}), 503
    
    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        asyncio.create_task(application.process_update(update))
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@flask_app.route('/')
def home():
    """Health check endpoint"""
    stats = get_stats()
    return jsonify({
        "status": "running",
        "bot": "Media Downloader Bot",
        "version": "4.0",
        "total_downloads": stats.get('total_downloads', 0),
        "uptime": "active"
    })

@flask_app.route('/health')
def health():
    """Detailed health check"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }), 200

# ==================== MAIN FUNCTION ====================
async def main_async():
    """Async main function"""
    global application
    
    # Create application with custom timeouts
    request_timeout = HTTPXRequest(
        connect_timeout=60.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=60.0
    )
    
    application = Application.builder()\
        .token(BOT_TOKEN)\
        .request(request_timeout)\
        .connect_timeout(60.0)\
        .read_timeout(60.0)\
        .write_timeout(60.0)\
        .build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Initialize application
    await application.initialize()
    await application.start()
    
    # Set webhook
    render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if render_hostname:
        webhook_url = f"https://{render_hostname}/webhook"
    else:
        # For local testing
        webhook_url = f"https://localhost:{PORT}/webhook"
    
    await application.bot.delete_webhook()
    await application.bot.set_webhook(webhook_url)
    
    logger.info(f"✅ Webhook set to: {webhook_url}")
    
    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║     ✅ MEDIA DOWNLOADER BOT V4.0 IS RUNNING!             ║
║                                                          ║
║     🤖 Bot: @MediaDownloaderBot                          ║
║     📡 Status: Webhook Active                            ║
║     📥 Ready to download!                                ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await application.stop()
        await application.shutdown()

def run_flask():
    """Run Flask server"""
    flask_app.run(host='0.0.0.0', port=PORT, threaded=False)

# ==================== ENTRY POINT ====================
if __name__ == "__main__":
    import threading
    
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Run bot
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n⚠️ Bot stopped by user!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")