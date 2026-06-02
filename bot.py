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
# आपने जो टोकन और आईडी दी है, वो यहाँ ऐड कर दी गई है
BOT_TOKEN = "8106042109:AAHaMFkdXkaH5EYrLKbQTCqSuoHH6ecM5zU"
OWNER_ID = 8679298308
PORT = int(os.getenv("PORT", 10000))

os.makedirs("downloads", exist_ok=True)
os.makedirs("data", exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)
application = None
executor = ThreadPoolExecutor(max_workers=5)
main_loop = None

# ==================== DATABASE ====================
def get_db(file_name):
    path = f"data/{file_name}.json"
    if not os.path.exists(path): return {}
    try:
        with open(path, 'r') as f: return json.load(f)
    except: return {}

def save_db(file_name, data):
    with open(f"data/{file_name}.json", 'w') as f: json.dump(data, f, indent=2)

def check_banned(user_id):
    users = get_db("users")
    return users.get(str(user_id), {}).get("banned", False)

# ==================== CORE DOWNLOADER ====================
def download_media(url, quality):
    try:
        # yt-dlp options optimized for Telegram's 50MB limit
        ydl_opts = {
            'outtmpl': 'downloads/%(title)s_%(id)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'restrictfilenames': True,
        }
        
        if quality == 'audio':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}]
        else:
            # Try to get requested quality, but prefer formats under 50MB
            ydl_opts['format'] = f'bestvideo[height<={quality}][filesize<50M][ext=mp4]+bestaudio[ext=m4a]/best[height<={quality}][filesize<50M][ext=mp4]/best'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            did = info.get('id')
            downloaded_file = next((f"downloads/{f}" for f in os.listdir("downloads") if did in f), None)
            
            if downloaded_file:
                size_mb = os.path.getsize(downloaded_file) / (1024 * 1024)
                if size_mb > 49.5:
                    os.remove(downloaded_file)
                    return {'error': f"⚠️ **फाइल बहुत बड़ी है ({size_mb:.1f}MB).**\nटेलीग्राम की लिमिट 50MB है। कृपया कोई कम रिज़ॉल्यूशन (जैसे 480p या 360p) चुनें।"}
                return {'path': downloaded_file, 'title': info.get('title', 'Media')[:60], 'size': round(size_mb, 1)}
        return {'error': "❌ मीडिया नहीं मिल सका।"}
    except Exception as e:
        return {'error': f"❌ Error: `{str(e)[:150]}`"}

# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if check_banned(user.id): return
    
    users = get_db("users")
    if str(user.id) not in users:
        users[str(user.id)] = {"name": user.first_name, "joined": str(datetime.now().date()), "banned": False}
        save_db("users", users)
    
    msg = (f"✨ **स्वागत है {user.first_name}!** (Premium 👑)\n\n"
           f"मैं इंटरनेट से कोई भी वीडियो या ऑडियो बेहतरीन क्वालिटी में डाउनलोड कर सकता हूँ।\n\n"
           f"🔗 **सपोर्टेड:** YouTube, Instagram, Facebook, TikTok, X (Twitter)\n"
           f"👇 बस मुझे कोई भी लिंक भेजें!")
    
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if check_banned(update.effective_user.id): return
    url = update.message.text.strip()
    if not url.startswith('http'):
        return await update.message.reply_text("❌ कृपया सही मीडिया लिंक भेजें (http/https से शुरू होने वाला)।")

    context.user_data['url'] = url
    
    # Premium Button UI
    kb = [
        [InlineKeyboardButton("📱 144p", callback_data="dl_144"), InlineKeyboardButton("📱 240p", callback_data="dl_240"), InlineKeyboardButton("📺 360p", callback_data="dl_360")],
        [InlineKeyboardButton("📺 480p", callback_data="dl_480"), InlineKeyboardButton("✨ 720p (HD)", callback_data="dl_720")],
        [InlineKeyboardButton("🔥 1080p (FHD)", callback_data="dl_1080"), InlineKeyboardButton("👑 4K (Max)", callback_data="dl_2160")],
        [InlineKeyboardButton("🎧 Premium Audio (MP3)", callback_data="dl_audio")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ]
    
    msg = f"✅ **लिंक मिल गया!**\n\n👇 अपनी मनपसंद क्वालिटी चुनें:"
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def progress_animation(msg_obj, stop_event):
    frames = [
        "🔄 **प्रोसेस हो रहा है...** [⬛⬛⬛⬛⬛]", 
        "🔄 **प्रोसेस हो रहा है...** [🟩⬛⬛⬛⬛]", 
        "🔄 **डाउनलोडिंग...** [🟩🟩⬛⬛⬛]", 
        "🔄 **डाउनलोडिंग...** [🟩🟩🟩⬛⬛]", 
        "🔄 **डाउनलोडिंग...** [🟩🟩🟩🟩⬛]", 
        "🔄 **तैयार हो रहा है...** [🟩🟩🟩🟩🟩]"
    ]
    i = 0
    while not stop_event.is_set():
        try:
            await msg_obj.edit_text(frames[i % len(frames)], parse_mode=ParseMode.MARKDOWN)
            i += 1
            await asyncio.sleep(1.2)
        except:
            break

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if check_banned(query.from_user.id): return await query.answer("आप बैन हैं।", show_alert=True)
    await query.answer()
    
    if query.data == "cancel_action":
        return await query.message.edit_text("🚫 **डाउनलोड कैंसल कर दिया गया।**", parse_mode=ParseMode.MARKDOWN)
    
    if query.data.startswith("dl_"):
        url = context.user_data.get('url')
        if not url: return await query.message.edit_text("❌ सेशन एक्सपायर हो गया। लिंक दोबारा भेजें।")
        
        quality = query.data.split('_')[1]
        p_msg = await query.message.edit_text("⏳ **शुरू हो रहा है...**", parse_mode=ParseMode.MARKDOWN)
        
        # Start Progress Animation
        stop_event = asyncio.Event()
        anim_task = asyncio.create_task(progress_animation(p_msg, stop_event))
        
        res = await asyncio.get_running_loop().run_in_executor(executor, download_media, url, quality)
        
        stop_event.set()
        await anim_task
        
        if 'error' in res:
            return await p_msg.edit_text(res['error'], parse_mode=ParseMode.MARKDOWN)
            
        try:
            await p_msg.edit_text("🚀 **टेलीग्राम पर अपलोड हो रहा है...**", parse_mode=ParseMode.MARKDOWN)
            with open(res['path'], 'rb') as f:
                cap = f"🎬 **{res['title']}**\n💾 साइज़: `{res['size']}MB`\n💎 @YourBotUsername"
                if quality == 'audio':
                    await context.bot.send_audio(chat_id=query.message.chat_id, audio=f, title=res['title'], caption=cap, parse_mode=ParseMode.MARKDOWN)
                else:
                    await context.bot.send_video(chat_id=query.message.chat_id, video=f, caption=cap, supports_streaming=True, parse_mode=ParseMode.MARKDOWN)
            
            os.remove(res['path'])
            await p_msg.delete()
            
            # Update Stats
            st = get_db("stats")
            st['downloads'] = st.get('downloads', 0) + 1
            save_db("stats", st)
            
        except Exception as e:
            await p_msg.edit_text(f"❌ अपलोड फेल हो गया: `{str(e)[:100]}`", parse_mode=ParseMode.MARKDOWN)
            if os.path.exists(res.get('path', '')): os.remove(res['path'])

# ==================== ADMIN ONLY COMMANDS ====================
async def is_owner(update: Update):
    if update.effective_user.id != OWNER_ID:
        return False
    return True

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_owner(update): return
    users = get_db("users")
    st = get_db("stats")
    msg = (f"👑 **Owner Dashboard**\n\n"
           f"👥 Total Users: `{len(users)}`\n"
           f"📥 Total Downloads: `{st.get('downloads', 0)}`\n\n"
           f"🛠 **Commands:**\n"
           f"`/ban <id>` - Ban user\n`/unban <id>` - Unban user\n"
           f"`/broadcast <msg>` - Send message to all")
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def admin_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_owner(update): return
    if not context.args: return await update.message.reply_text("⚠️ Usage: `/ban <user_id>`")
    uid = context.args[0]
    users = get_db("users")
    if uid in users:
        users[uid]['banned'] = True
        save_db("users", users)
        await update.message.reply_text(f"✅ User {uid} Banned.")
    else: await update.message.reply_text("❌ User not found.")

async def admin_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_owner(update): return
    if not context.args: return await update.message.reply_text("⚠️ Usage: `/unban <user_id>`")
    uid = context.args[0]
    users = get_db("users")
    if uid in users:
        users[uid]['banned'] = False
        save_db("users", users)
        await update.message.reply_text(f"✅ User {uid} Unbanned.")
    else: await update.message.reply_text("❌ User not found.")

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_owner(update): return
    msg = " ".join(context.args)
    if not msg: return await update.message.reply_text("⚠️ Usage: `/broadcast Hello everyone!`")
    
    users = get_db("users")
    m = await update.message.reply_text("⏳ Broadcasting...")
    sent, failed = 0, 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"📢 **Admin Update**\n\n{msg}", parse_mode=ParseMode.MARKDOWN)
            sent += 1
            await asyncio.sleep(0.05)
        except: failed += 1
    await m.edit_text(f"✅ Broadcast Done!\nSent: {sent} | Failed: {failed}")

# ==================== FLASK & RUNNER ====================
@flask_app.route('/webhook', methods=['POST'])
def webhook():
    if application and main_loop:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)
        asyncio.run_coroutine_threadsafe(application.process_update(update), main_loop)
    return jsonify({"status": "ok"}), 200

@flask_app.route('/')
def home(): return "V2 Premium Bot is Running!"

async def main_async():
    global application, main_loop
    main_loop = asyncio.get_running_loop()
    req = HTTPXRequest(connect_timeout=60.0, read_timeout=60.0)
    application = Application.builder().token(BOT_TOKEN).request(req).updater(None).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("hidden", admin_panel))
    application.add_handler(CommandHandler("ban", admin_ban))
    application.add_handler(CommandHandler("unban", admin_unban))
    application.add_handler(CommandHandler("broadcast", admin_broadcast))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
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
    try: asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit): pass
