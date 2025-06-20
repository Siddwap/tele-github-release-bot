import logging
import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import BotConfig
from main_bot_integration import initialize_bot_integration, bot_integration
from m3u8_downloader import M3U8Downloader
from github_uploader import GitHubUploader
import asyncio

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize config
config = BotConfig()

# Initialize bot integration
initialize_bot_integration(config)

# Initialize GitHub uploader
github_uploader = GitHubUploader(
    token=config.github_token,
    repo=config.github_repo,
    release_tag=config.github_release_tag
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        "🎉 Welcome to File Uploader Bot!\n\n"
        "I can help you upload files to GitHub and download M3U8 streams.\n\n"
        "Use /help to see all available commands."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = """
🤖 **File Uploader Bot Help**

**Basic Commands:**
• /start - Start the bot
• /help - Show this help message

**M3U8 Download Commands:**
• Send M3U8 URL - Download and upload M3U8 stream
• Send M3U8 file - Process M3U8 playlist file

**File Upload Commands:**
• Send any file - Upload to GitHub and get download link

**TXT File Commands:**
• /txt_upload - Upload files from txt file (filename:url format)
• /txt_links - Upload files and get GitHub links in txt format
• /txt_help - Detailed txt upload help

**Features:**
• ✅ High-speed downloads with progress tracking
• ✅ Automatic GitHub upload and link generation
• ✅ Support for MP4, PDF, M3U8, and other file types
• ✅ Bulk upload from txt files
• ✅ Download speed and progress indicators

**Example txt file format:**
```
movie.mp4 : https://example.com/movie.mp4
document.pdf : https://example.com/doc.pdf
playlist.m3u8 : https://example.com/stream.m3u8
```

Need help? Just send me a file or M3U8 link to get started!
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all messages"""
    try:
        # Check if our integration handles this message FIRST
        if bot_integration and await bot_integration.handle_message(update, context):
            return  # Message was handled, don't process further
        
        # Handle M3U8 URL
        if update.message.text and update.message.text.strip().startswith('http'):
            m3u8_url = update.message.text.strip()
            status_message = await update.message.reply_text("Downloading M3U8 stream...")
            
            async def progress_callback(message):
                try:
                    await status_message.edit_text(message)
                except:
                    pass  # Ignore edit errors
            
            try:
                downloader = M3U8Downloader()
                file_path = await downloader.download_m3u8(m3u8_url, progress_callback=progress_callback)
                
                await status_message.edit_text("Uploading to GitHub...")
                github_url = await github_uploader.upload_file(file_path)
                await status_message.edit_text(f"✅ Uploaded to GitHub!\n\n🔗 Download Link: {github_url}")
                
                os.remove(file_path)  # Clean up temp file
            except Exception as e:
                logger.error(f"Error downloading M3U8: {e}")
                await status_message.edit_text(f"❌ Error downloading M3U8: {str(e)}")
            return
        
        # Handle M3U8 file upload
        if update.message.document and update.message.document.file_name.endswith('.m3u8'):
            file_id = update.message.document.file_id
            file = await context.bot.get_file(file_id)
            file_path = await file.download_as_bytearray()
            
            status_message = await update.message.reply_text("Downloading M3U8 stream...")
            
            async def progress_callback(message):
                try:
                    await status_message.edit_text(message)
                except:
                    pass  # Ignore edit errors
            
            try:
                downloader = M3U8Downloader()
                temp_file_path = await downloader.download_m3u8_from_content(file_path, progress_callback=progress_callback)
                
                await status_message.edit_text("Uploading to GitHub...")
                github_url = await github_uploader.upload_file(temp_file_path)
                await status_message.edit_text(f"✅ Uploaded to GitHub!\n\n🔗 Download Link: {github_url}")
                
                os.remove(temp_file_path)  # Clean up temp file
            except Exception as e:
                logger.error(f"Error downloading M3U8: {e}")
                await status_message.edit_text(f"❌ Error downloading M3U8: {str(e)}")
            return
        
        # Handle regular file upload
        if update.message.document:
            file_id = update.message.document.file_id
            file_name = update.message.document.file_name
            status_message = await update.message.reply_text(f"Downloading {file_name}...")
            
            try:
                file = await context.bot.get_file(file_id)
                file_path = await file.download_as_bytearray()
                
                await status_message.edit_text(f"Uploading {file_name} to GitHub...")
                github_url = await github_uploader.upload_asset(file_path, file_name)
                await status_message.edit_text(f"✅ Uploaded {file_name} to GitHub!\n\n🔗 Download Link: {github_url}")
            except Exception as e:
                logger.error(f"Error uploading file: {e}")
                await status_message.edit_text(f"❌ Error uploading file: {str(e)}")
            return
        
        # Handle unknown message
        await update.message.reply_text("🤔 I don't understand that message. Send /help for available commands.")
        
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await update.message.reply_text(f"❌ An error occurred: {str(e)}")

def main():
    """Start the bot."""
    # Create application
    application = Application.builder().token(config.telegram_token).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.ALL, handle_message))

    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
