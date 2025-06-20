
import logging
import os
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename
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

class TelegramBot:
    def __init__(self):
        # Initialize config
        self.config = BotConfig.from_env()
        
        # Initialize bot integration
        initialize_bot_integration(self.config)
        
        # Initialize GitHub uploader
        self.github_uploader = GitHubUploader(
            token=self.config.github_token,
            repo=self.config.github_repo,
            release_tag=self.config.github_release_tag
        )
        
        # Initialize Telethon client
        self.client = TelegramClient(
            'bot_session',
            self.config.telegram_api_id,
            self.config.telegram_api_hash
        )
        
        # Register event handlers
        self.client.add_event_handler(self.handle_start, events.NewMessage(pattern='/start'))
        self.client.add_event_handler(self.handle_help, events.NewMessage(pattern='/help'))
        self.client.add_event_handler(self.handle_message, events.NewMessage())
    
    async def handle_start(self, event):
        """Handle /start command"""
        await event.respond(
            "🎉 Welcome to File Uploader Bot!\n\n"
            "I can help you upload files to GitHub and download M3U8 streams.\n\n"
            "Use /help to see all available commands."
        )
    
    async def handle_help(self, event):
        """Handle /help command"""
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
        await event.respond(help_text)
    
    async def handle_message(self, event):
        """Handle all messages"""
        try:
            # Check if our integration handles this message FIRST
            if bot_integration and await bot_integration.handle_message(event):
                return  # Message was handled, don't process further
            
            # Handle M3U8 URL
            if event.message.text and event.message.text.strip().startswith('http'):
                m3u8_url = event.message.text.strip()
                status_message = await event.respond("Downloading M3U8 stream...")
                
                async def progress_callback(message):
                    try:
                        await status_message.edit(message)
                    except:
                        pass  # Ignore edit errors
                
                try:
                    downloader = M3U8Downloader()
                    file_path = await downloader.download_m3u8(m3u8_url, progress_callback=progress_callback)
                    
                    await status_message.edit("Uploading to GitHub...")
                    github_url = await self.github_uploader.upload_file(file_path)
                    await status_message.edit(f"✅ Uploaded to GitHub!\n\n🔗 Download Link: {github_url}")
                    
                    os.remove(file_path)  # Clean up temp file
                except Exception as e:
                    logger.error(f"Error downloading M3U8: {e}")
                    await status_message.edit(f"❌ Error downloading M3U8: {str(e)}")
                return
            
            # Handle M3U8 file upload
            if event.message.document and event.message.document.mime_type == 'application/x-mpegURL':
                file_id = event.message.document.id
                file_path = await event.message.download_media()
                
                status_message = await event.respond("Downloading M3U8 stream...")
                
                async def progress_callback(message):
                    try:
                        await status_message.edit(message)
                    except:
                        pass  # Ignore edit errors
                
                try:
                    downloader = M3U8Downloader()
                    temp_file_path = await downloader.download_m3u8_from_file(file_path, progress_callback=progress_callback)
                    
                    await status_message.edit("Uploading to GitHub...")
                    github_url = await self.github_uploader.upload_file(temp_file_path)
                    await status_message.edit(f"✅ Uploaded to GitHub!\n\n🔗 Download Link: {github_url}")
                    
                    os.remove(temp_file_path)  # Clean up temp file
                    os.remove(file_path)  # Clean up downloaded file
                except Exception as e:
                    logger.error(f"Error downloading M3U8: {e}")
                    await status_message.edit(f"❌ Error downloading M3U8: {str(e)}")
                return
            
            # Handle regular file upload
            if event.message.document:
                file_name = "unknown_file"
                for attr in event.message.document.attributes:
                    if isinstance(attr, DocumentAttributeFilename):
                        file_name = attr.file_name
                        break
                
                status_message = await event.respond(f"Downloading {file_name}...")
                
                try:
                    file_path = await event.message.download_media()
                    
                    await status_message.edit(f"Uploading {file_name} to GitHub...")
                    
                    with open(file_path, 'rb') as f:
                        file_data = f.read()
                    
                    github_url = await self.github_uploader.upload_asset(file_data, file_name)
                    await status_message.edit(f"✅ Uploaded {file_name} to GitHub!\n\n🔗 Download Link: {github_url}")
                    
                    os.remove(file_path)  # Clean up temp file
                except Exception as e:
                    logger.error(f"Error uploading file: {e}")
                    await status_message.edit(f"❌ Error uploading file: {str(e)}")
                return
            
            # Handle unknown message
            if not event.message.text.startswith('/'):
                await event.respond("🤔 I don't understand that message. Send /help for available commands.")
            
        except Exception as e:
            logger.error(f"Error in handle_message: {e}")
            await event.respond(f"❌ An error occurred: {str(e)}")
    
    async def start(self):
        """Start the bot"""
        await self.client.start(bot_token=self.config.telegram_bot_token)
        logger.info("Bot started successfully!")
        await self.client.run_until_disconnected()

def main():
    """Main entry point"""
    bot = TelegramBot()
    asyncio.run(bot.start())

if __name__ == '__main__':
    main()
