
import asyncio
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional, BinaryIO
import aiohttp
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename
from dotenv import load_dotenv
from github_uploader import GitHubUploader
import time

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.api_id = int(os.getenv('TELEGRAM_API_ID'))
        self.api_hash = os.getenv('TELEGRAM_API_HASH')
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.github_token = os.getenv('GITHUB_TOKEN')
        self.github_repo = os.getenv('GITHUB_REPO')
        self.github_release_tag = os.getenv('GITHUB_RELEASE_TAG')
        
        if not all([self.api_id, self.api_hash, self.bot_token, self.github_token, self.github_repo, self.github_release_tag]):
            raise ValueError("Missing required environment variables")
        
        self.client = TelegramClient('bot', self.api_id, self.api_hash)
        self.github_uploader = GitHubUploader(self.github_token, self.github_repo, self.github_release_tag)
        self.active_uploads = {}

    async def start(self):
        """Start the bot"""
        try:
            await self.client.start(bot_token=self.bot_token)
            logger.info("Bot started successfully")
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            raise
        
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            await event.respond(
                "🤖 **GitHub Release Uploader Bot**\n\n"
                "Send me a file or a URL to upload to GitHub release!\n\n"
                "**Commands:**\n"
                "• Send any file (up to 4GB)\n"
                "• Send a URL to download and upload\n"
                "• /help - Show this message\n"
                "• /status - Check upload status"
            )
            raise events.StopPropagation

        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            await event.respond(
                "**How to use:**\n\n"
                "1. **File Upload**: Send any file directly to the bot\n"
                "2. **URL Upload**: Send a URL pointing to a file\n\n"
                "**Features:**\n"
                "• Supports files up to 4GB\n"
                "• Real-time progress updates with speed\n"
                "• Direct upload to GitHub releases\n"
                "• Returns download URL after upload\n\n"
                f"**Target Repository:** `{self.github_repo}`\n"
                f"**Release Tag:** `{self.github_release_tag}`"
            )
            raise events.StopPropagation

        @self.client.on(events.NewMessage(pattern='/status'))
        async def status_handler(event):
            user_id = event.sender_id
            if user_id in self.active_uploads:
                upload_info = self.active_uploads[user_id]
                await event.respond(f"📊 Active upload: {upload_info['filename']} - {upload_info['status']}")
            else:
                await event.respond("No active uploads")
            raise events.StopPropagation

        @self.client.on(events.NewMessage)
        async def message_handler(event):
            # Skip if it's a command (already handled by specific handlers)
            if event.message.text and event.message.text.startswith('/'):
                return
            
            user_id = event.sender_id
            
            # Check if user has active upload
            if user_id in self.active_uploads:
                await event.respond("⚠️ You have an active upload. Please wait for it to complete.")
                return

            try:
                # Handle file uploads
                if event.message.document:
                    await self.handle_file_upload(event)
                    return
                
                # Handle URL messages
                if event.message.text:
                    text = event.message.text.strip()
                    if self.is_url(text):
                        await self.handle_url_upload(event)
                        return
                    
                    # Only respond to non-empty text that's not a URL or command
                    if text and not text.startswith('/'):
                        await event.respond(
                            "❓ **Invalid Input**\n\n"
                            "Please send:\n"
                            "• A file (drag & drop or attach)\n"
                            "• A direct download URL\n\n"
                            "Use /help for more information."
                        )
                
                # Ignore other message types (stickers, photos without documents, etc.)
                
            except Exception as e:
                logger.error(f"Error handling message from user {user_id}: {e}")
                await event.respond(f"❌ **Error**\n\nSomething went wrong: {str(e)}")
                if user_id in self.active_uploads:
                    del self.active_uploads[user_id]

        try:
            await self.client.run_until_disconnected()
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
        except Exception as e:
            logger.error(f"Bot disconnected with error: {e}")

    def is_url(self, text: str) -> bool:
        """Check if text is a valid URL"""
        if not text:
            return False
        return text.startswith(('http://', 'https://')) and len(text) > 8

    async def handle_file_upload(self, event):
        """Handle file upload from Telegram using temporary file streaming"""
        user_id = event.sender_id
        document = event.message.document
        
        # Get filename
        filename = "unknown_file"
        for attr in document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                filename = attr.file_name
                break
        
        file_size = document.size
        logger.info(f"Receiving file: {filename}, size: {file_size} bytes")
        
        # Check file size (4GB limit)
        if file_size > 4 * 1024 * 1024 * 1024:
            await event.respond("❌ File too large. Maximum size is 4GB.")
            return

        self.active_uploads[user_id] = {
            'filename': filename,
            'status': 'Starting download...'
        }

        progress_msg = await event.respond("📥 **Downloading from Telegram...**\n⏳ Starting...")
        
        # Use temporary file for streaming
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            try:
                # Download file with progress to temporary file
                await self.download_telegram_file_streaming(document, temp_file, progress_msg, filename)
                
                # Upload to GitHub from temporary file
                await progress_msg.edit("📤 **Uploading to GitHub...**\n⏳ Starting...")
                download_url = await self.upload_to_github_streaming(temp_file.name, filename, file_size, progress_msg)
                
                await progress_msg.edit(
                    f"✅ **Upload Complete!**\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}"
                )
                
            except Exception as e:
                logger.error(f"Error uploading file: {e}")
                await progress_msg.edit(f"❌ **Upload Failed**\n\nError: {str(e)}")
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
                if user_id in self.active_uploads:
                    del self.active_uploads[user_id]

    async def handle_url_upload(self, event):
        """Handle URL download and upload using streaming"""
        user_id = event.sender_id
        url = event.message.text.strip()
        
        # Extract filename from URL
        filename = url.split('/')[-1] or f"download_{int(time.time())}"
        if '?' in filename:
            filename = filename.split('?')[0]
        
        logger.info(f"Downloading from URL: {url}")
        
        self.active_uploads[user_id] = {
            'filename': filename,
            'status': 'Starting download...'
        }

        progress_msg = await event.respond("📥 **Downloading from URL...**\n⏳ Starting...")
        
        # Use temporary file for streaming
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            try:
                # Download from URL with progress to temporary file
                file_size = await self.download_from_url_streaming(url, temp_file, progress_msg, filename)
                
                # Upload to GitHub from temporary file
                await progress_msg.edit("📤 **Uploading to GitHub...**\n⏳ Starting...")
                download_url = await self.upload_to_github_streaming(temp_file.name, filename, file_size, progress_msg)
                
                await progress_msg.edit(
                    f"✅ **Upload Complete!**\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}"
                )
                
            except Exception as e:
                logger.error(f"Error processing URL: {e}")
                await progress_msg.edit(f"❌ **Upload Failed**\n\nError: {str(e)}")
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
                if user_id in self.active_uploads:
                    del self.active_uploads[user_id]

    async def download_telegram_file_streaming(self, document, temp_file, progress_msg, filename: str):
        """Download file from Telegram with progress and speed using streaming to temp file"""
        total_size = document.size
        downloaded = 0
        start_time = time.time()
        last_update_time = start_time
        last_downloaded = 0
        
        async def progress_callback(current, total):
            nonlocal downloaded, last_update_time, last_downloaded
            downloaded = current
            current_time = time.time()
            progress = (current / total) * 100
            
            # Calculate speed
            time_diff = current_time - last_update_time
            bytes_diff = current - last_downloaded
            speed = bytes_diff / time_diff if time_diff > 0 else 0
            
            # Update every 2% progress or every 2 seconds
            if progress - getattr(progress_callback, 'last_progress', 0) >= 2 or time_diff >= 2:
                await progress_msg.edit(
                    f"📥 **Downloading from Telegram...**\n\n"
                    f"📁 {filename}\n"
                    f"📊 {self.format_size(current)} / {self.format_size(total)}\n"
                    f"⏳ {progress:.1f}%\n"
                    f"🚀 Speed: {self.format_size(speed)}/s\n"
                    f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
                )
                progress_callback.last_progress = progress
                last_update_time = current_time
                last_downloaded = current
        
        # Download file to temporary file using streaming
        await self.client.download_media(document, file=temp_file, progress_callback=progress_callback)

    async def download_from_url_streaming(self, url: str, temp_file, progress_msg, filename: str) -> int:
        """Download file from URL with progress and speed using streaming to temp file"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download: HTTP {response.status}")
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                start_time = time.time()
                last_update_time = start_time
                last_downloaded = 0
                
                async for chunk in response.content.iter_chunked(1024 * 1024):  # 1MB chunks
                    temp_file.write(chunk)
                    downloaded += len(chunk)
                    current_time = time.time()
                    
                    if total_size > 0:
                        progress = (downloaded / total_size) * 100
                        
                        # Calculate speed
                        time_diff = current_time - last_update_time
                        bytes_diff = downloaded - last_downloaded
                        speed = bytes_diff / time_diff if time_diff > 0 else 0
                        
                        # Update every 2% progress or every 2 seconds
                        if progress - getattr(self, '_last_url_progress', 0) >= 2 or time_diff >= 2:
                            await progress_msg.edit(
                                f"📥 **Downloading from URL...**\n\n"
                                f"📁 {filename}\n"
                                f"📊 {self.format_size(downloaded)} / {self.format_size(total_size)}\n"
                                f"⏳ {progress:.1f}%\n"
                                f"🚀 Speed: {self.format_size(speed)}/s\n"
                                f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
                            )
                            self._last_url_progress = progress
                            last_update_time = current_time
                            last_downloaded = downloaded
                
                temp_file.flush()
                return downloaded

    async def upload_to_github_streaming(self, temp_file_path: str, filename: str, file_size: int, progress_msg) -> str:
        """Upload file to GitHub with progress and speed using streaming"""
        uploaded = 0
        start_time = time.time()
        last_update_time = start_time
        last_uploaded = 0
        
        async def progress_callback(current: int):
            nonlocal uploaded, last_update_time, last_uploaded
            uploaded = current
            current_time = time.time()
            progress = (current / file_size) * 100
            
            # Calculate speed
            time_diff = current_time - last_update_time
            bytes_diff = current - last_uploaded
            speed = bytes_diff / time_diff if time_diff > 0 else 0
            
            # Update every 2% progress or every 2 seconds
            if progress - getattr(progress_callback, 'last_progress', 0) >= 2 or time_diff >= 2:
                await progress_msg.edit(
                    f"📤 **Uploading to GitHub...**\n\n"
                    f"📁 {filename}\n"
                    f"📊 {self.format_size(current)} / {self.format_size(file_size)}\n"
                    f"⏳ {progress:.1f}%\n"
                    f"🚀 Speed: {self.format_size(speed)}/s\n"
                    f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
                )
                progress_callback.last_progress = progress
                last_update_time = current_time
                last_uploaded = current
        
        return await self.github_uploader.upload_asset_streaming(temp_file_path, filename, file_size, progress_callback)

    def format_size(self, size: int) -> str:
        """Format file size in human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"

async def main():
    bot = TelegramBot()
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())
