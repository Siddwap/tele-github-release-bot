import asyncio
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional, BinaryIO, Dict, List
from collections import deque
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
        self.upload_queues: Dict[int, deque] = {}  # User ID -> queue of uploads
        self.processing_queues: Dict[int, bool] = {}  # User ID -> is processing

    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename by replacing special characters while preserving extension"""
        import re
        
        # Split filename and extension
        if '.' in filename:
            name_part = '.'.join(filename.split('.')[:-1])
            extension = filename.split('.')[-1]
        else:
            name_part = filename
            extension = ''
        
        # Replace special characters with safe alternatives
        # Keep only alphanumeric, spaces, dots, hyphens, and underscores
        name_part = re.sub(r'[^\w\s\-_.]', '_', name_part)
        
        # Replace multiple spaces/underscores with single underscore
        name_part = re.sub(r'[\s_]+', '_', name_part)
        
        # Remove leading/trailing underscores
        name_part = name_part.strip('_')
        
        # Reconstruct filename with extension
        if extension:
            return f"{name_part}.{extension}"
        else:
            return name_part

    async def add_to_queue(self, user_id: int, upload_item: dict):
        """Add upload item to user's queue"""
        if user_id not in self.upload_queues:
            self.upload_queues[user_id] = deque()
        
        self.upload_queues[user_id].append(upload_item)
        await self.process_queue(user_id)

    async def process_queue(self, user_id: int):
        """Process upload queue for a user"""
        if user_id in self.processing_queues and self.processing_queues[user_id]:
            return  # Already processing
        
        if user_id not in self.upload_queues or not self.upload_queues[user_id]:
            return  # No items in queue
        
        self.processing_queues[user_id] = True
        
        try:
            while self.upload_queues[user_id]:
                upload_item = self.upload_queues[user_id].popleft()
                
                # Update active uploads
                self.active_uploads[user_id] = {
                    'filename': upload_item['filename'],
                    'status': f"Processing... ({len(self.upload_queues[user_id])} remaining in queue)"
                }
                
                if upload_item['type'] == 'file':
                    await self.process_file_upload(upload_item)
                elif upload_item['type'] == 'url':
                    await self.process_url_upload(upload_item)
                
        except Exception as e:
            logger.error(f"Error processing queue for user {user_id}: {e}")
        finally:
            self.processing_queues[user_id] = False
            if user_id in self.active_uploads:
                del self.active_uploads[user_id]

    async def process_file_upload(self, upload_item: dict):
        """Process a single file upload from queue"""
        event = upload_item['event']
        document = upload_item['document']
        filename = upload_item['filename']
        file_size = upload_item['file_size']
        user_id = upload_item['user_id']
        
        progress_msg = await event.respond("📥 **Downloading from Telegram...**\n⏳ Starting...")
        
        # Use temporary file for streaming
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            try:
                # Download file with progress to temporary file
                await self.download_telegram_file_streaming(document, temp_file, progress_msg, filename)
                
                # Upload to GitHub from temporary file
                await progress_msg.edit("📤 **Uploading to GitHub...**\n⏳ Starting...")
                download_url = await self.upload_to_github_streaming(temp_file.name, filename, file_size, progress_msg)
                
                remaining = len(self.upload_queues.get(user_id, []))
                queue_text = f"\n\n📋 **Queue:** {remaining} files remaining" if remaining > 0 else ""
                
                await progress_msg.edit(
                    f"✅ **Upload Complete!**\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}{queue_text}"
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

    async def process_url_upload(self, upload_item: dict):
        """Process a single URL upload from queue"""
        event = upload_item['event']
        url = upload_item['url']
        filename = upload_item['filename']
        user_id = upload_item['user_id']
        
        progress_msg = await event.respond("📥 **Downloading from URL...**\n⏳ Starting...")
        
        # Use temporary file for streaming
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            try:
                # Download from URL with progress to temporary file
                file_size = await self.download_from_url_streaming(url, temp_file, progress_msg, filename)
                
                # Upload to GitHub from temporary file
                await progress_msg.edit("📤 **Uploading to GitHub...**\n⏳ Starting...")
                download_url = await self.upload_to_github_streaming(temp_file.name, filename, file_size, progress_msg)
                
                remaining = len(self.upload_queues.get(user_id, []))
                queue_text = f"\n\n📋 **Queue:** {remaining} files remaining" if remaining > 0 else ""
                
                await progress_msg.edit(
                    f"✅ **Upload Complete!**\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}{queue_text}"
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
                "Send me files or URLs to upload to GitHub release!\n\n"
                "**Features:**\n"
                "• Send multiple files - they'll upload one by one\n"
                "• Send multiple URLs - processed in order\n"
                "• Real-time progress with speed display\n"
                "• Queue system for batch uploads\n\n"
                "**Commands:**\n"
                "• Send any file (up to 4GB)\n"
                "• Send a URL to download and upload\n"
                "• /help - Show this message\n"
                "• /status - Check upload status\n"
                "• /queue - Check queue status"
            )
            raise events.StopPropagation

        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            await event.respond(
                "**How to use:**\n\n"
                "1. **File Upload**: Send any file directly to the bot\n"
                "2. **URL Upload**: Send a URL pointing to a file\n"
                "3. **Batch Upload**: Send multiple files/URLs - they'll queue automatically\n\n"
                "**Features:**\n"
                "• Supports files up to 4GB\n"
                "• Real-time progress updates with speed\n"
                "• Queue system for multiple uploads\n"
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

        @self.client.on(events.NewMessage(pattern='/queue'))
        async def queue_handler(event):
            user_id = event.sender_id
            if user_id in self.upload_queues and self.upload_queues[user_id]:
                queue_count = len(self.upload_queues[user_id])
                queue_items = []
                for i, item in enumerate(list(self.upload_queues[user_id])[:5]):  # Show first 5
                    queue_items.append(f"{i+1}. {item['filename']}")
                
                queue_text = "\n".join(queue_items)
                if queue_count > 5:
                    queue_text += f"\n... and {queue_count - 5} more"
                
                await event.respond(f"📋 **Upload Queue ({queue_count} items):**\n\n{queue_text}")
            else:
                await event.respond("📋 Queue is empty")
            raise events.StopPropagation

        @self.client.on(events.NewMessage)
        async def message_handler(event):
            # Skip if it's a command (already handled by specific handlers)
            if event.message.text and event.message.text.startswith('/'):
                return
            
            user_id = event.sender_id

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
        """Handle file upload by adding to queue"""
        user_id = event.sender_id
        document = event.message.document
        
        # Get filename
        filename = "unknown_file"
        for attr in document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                filename = attr.file_name
                break
        
        # Sanitize filename to avoid GitHub upload issues
        sanitized_filename = self.sanitize_filename(filename)
        if sanitized_filename != filename:
            logger.info(f"Sanitized filename: '{filename}' -> '{sanitized_filename}'")
        
        file_size = document.size
        logger.info(f"Queuing file: {sanitized_filename}, size: {file_size} bytes")
        
        # Check file size (4GB limit)
        if file_size > 4 * 1024 * 1024 * 1024:
            await event.respond("❌ File too large. Maximum size is 4GB.")
            return

        # Add to queue
        upload_item = {
            'type': 'file',
            'event': event,
            'document': document,
            'filename': sanitized_filename,
            'file_size': file_size,
            'user_id': user_id
        }
        
        queue_position = len(self.upload_queues.get(user_id, [])) + 1
        await event.respond(f"📋 **File Queued**\n\n📁 **File:** `{sanitized_filename}`\n📊 **Size:** {self.format_size(file_size)}\n🔢 **Position:** {queue_position}")
        
        await self.add_to_queue(user_id, upload_item)

    async def handle_url_upload(self, event):
        """Handle URL upload by adding to queue"""
        user_id = event.sender_id
        url = event.message.text.strip()
        
        # Extract filename from URL
        filename = url.split('/')[-1] or f"download_{int(time.time())}"
        if '?' in filename:
            filename = filename.split('?')[0]
        
        # Sanitize filename to avoid GitHub upload issues
        sanitized_filename = self.sanitize_filename(filename)
        if sanitized_filename != filename:
            logger.info(f"Sanitized filename: '{filename}' -> '{sanitized_filename}'")
        
        logger.info(f"Queuing URL: {url}")
        
        # Add to queue
        upload_item = {
            'type': 'url',
            'event': event,
            'url': url,
            'filename': sanitized_filename,
            'user_id': user_id
        }
        
        queue_position = len(self.upload_queues.get(user_id, [])) + 1
        await event.respond(f"📋 **URL Queued**\n\n🔗 **URL:** `{url}`\n📁 **File:** `{sanitized_filename}`\n🔢 **Position:** {queue_position}")
        
        await self.add_to_queue(user_id, upload_item)

    async def download_telegram_file_streaming(self, document, temp_file, progress_msg, filename: str):
        """Download file from Telegram with progress and speed using streaming to temp file - OPTIMIZED"""
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
        
        # Download file to temporary file using streaming (removed unsupported chunk_size parameter)
        await self.client.download_media(
            document, 
            file=temp_file, 
            progress_callback=progress_callback
        )

    async def download_from_url_streaming(self, url: str, temp_file, progress_msg, filename: str) -> int:
        """Download file from URL with progress and speed using streaming to temp file - OPTIMIZED"""
        # Optimized aiohttp session with better settings for high-speed downloads
        timeout = aiohttp.ClientTimeout(total=None, connect=30)
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=30,
            ttl_dns_cache=300,
            use_dns_cache=True,
            enable_cleanup_closed=True
        )
        
        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        ) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download: HTTP {response.status}")
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                start_time = time.time()
                last_update_time = start_time
                last_downloaded = 0
                
                # Increased chunk size for better performance
                chunk_size = 8 * 1024 * 1024  # 8MB chunks
                
                async for chunk in response.content.iter_chunked(chunk_size):
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
