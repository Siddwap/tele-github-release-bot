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
from telethon.tl.custom import Button
from dotenv import load_dotenv
from github_uploader import GitHubUploader
from config import BotConfig
from m3u8_handler import M3U8Handler
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
        self.config = BotConfig.from_env()
        self.config.validate()
        
        self.client = TelegramClient('bot', self.config.telegram_api_id, self.config.telegram_api_hash)
        self.github_uploader = GitHubUploader(self.config.github_token, self.config.github_repo, self.config.github_release_tag)
        self.m3u8_handler = M3U8Handler()
        self.active_uploads = {}
        self.upload_queues: Dict[int, deque] = {}  # User ID -> queue of uploads
        self.processing_queues: Dict[int, bool] = {}  # User ID -> is processing
        self.should_stop = False  # Flag to control stopping processes
        self.active_sessions: Dict[int, List] = {}  # User ID -> list of active aiohttp sessions
        self.pending_quality_selection: Dict[int, Dict] = {}  # User ID -> {url, qualities, event}

    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin"""
        return self.config.is_admin(user_id)

    async def stop_all_processes(self):
        """Stop all running processes"""
        self.should_stop = True
        
        # Cancel all active aiohttp sessions
        for user_id, sessions in self.active_sessions.items():
            for session in sessions:
                if not session.closed:
                    await session.close()
        self.active_sessions.clear()
        
        # Clear all queues
        for user_id in list(self.upload_queues.keys()):
            self.upload_queues[user_id].clear()
        
        # Stop processing
        for user_id in list(self.processing_queues.keys()):
            self.processing_queues[user_id] = False
        
        # Clear active uploads
        self.active_uploads.clear()
        
        # Clear pending quality selections
        self.pending_quality_selection.clear()
        
        logger.info("All processes stopped by admin command")

    async def restart_all_processes(self):
        """Restart all processes"""
        self.should_stop = False
        logger.info("All processes restarted by admin command")

    def add_active_session(self, user_id: int, session):
        """Add an active session for tracking"""
        if user_id not in self.active_sessions:
            self.active_sessions[user_id] = []
        self.active_sessions[user_id].append(session)

    def remove_active_session(self, user_id: int, session):
        """Remove an active session"""
        if user_id in self.active_sessions and session in self.active_sessions[user_id]:
            self.active_sessions[user_id].remove(session)

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

    async def parse_batch_file(self, file_content: str) -> List[Dict]:
        """Parse batch file content to extract video names and URLs"""
        batch_items = []
        lines = file_content.strip().split('\n')
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):  # Skip empty lines and comments
                continue
            
            # Parse format: video_name : url
            if ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    video_name = parts[0].strip()
                    url = parts[1].strip()
                    
                    if self.is_url(url) and video_name:
                        # Sanitize filename
                        if not video_name.endswith(('.mp4', '.mkv', '.avi', '.mov')):
                            video_name += '.mp4'
                        
                        sanitized_name = self.sanitize_filename(video_name)
                        
                        batch_items.append({
                            'name': sanitized_name,
                            'url': url,
                            'line': line_num
                        })
            
        return batch_items

    async def add_to_queue(self, user_id: int, upload_item: dict):
        """Add upload item to user's queue"""
        if self.should_stop:
            return
            
        if user_id not in self.upload_queues:
            self.upload_queues[user_id] = deque()
        
        self.upload_queues[user_id].append(upload_item)
        await self.process_queue(user_id)

    async def process_queue(self, user_id: int):
        """Process upload queue for a user"""
        if self.should_stop or (user_id in self.processing_queues and self.processing_queues[user_id]):
            return  # Already processing or stopped
        
        if user_id not in self.upload_queues or not self.upload_queues[user_id]:
            return  # No items in queue
        
        self.processing_queues[user_id] = True
        
        try:
            while self.upload_queues[user_id] and not self.should_stop:
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
                elif upload_item['type'] == 'm3u8':
                    await self.process_m3u8_upload(upload_item)
                elif upload_item['type'] == 'batch':
                    await self.process_batch_upload(upload_item)
                
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

    async def process_m3u8_upload(self, upload_item: dict):
        """Process a single M3U8 upload from queue"""
        event = upload_item['event']
        url = upload_item['url']
        filename = upload_item['filename']
        user_id = upload_item['user_id']
        selected_quality = upload_item.get('quality')
        
        progress_msg = await event.respond("📥 **Processing M3U8 video...**\n⏳ Starting...")
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
            try:
                # Download M3U8 video with progress
                async def m3u8_progress_callback(progress, segment_num, total_segments, total_downloaded):
                    if self.should_stop:
                        raise Exception("Upload stopped by admin command")
                    
                    await progress_msg.edit(
                        f"📥 **Downloading M3U8 video...**\n\n"
                        f"📁 {filename}\n"
                        f"📊 Segments: {segment_num}/{total_segments}\n"
                        f"⏳ {progress:.1f}%\n"
                        f"💾 Downloaded: {self.format_size(total_downloaded)}\n"
                        f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
                    )
                
                file_size = await self.m3u8_handler.download_m3u8_video(
                    url, temp_file.name, selected_quality, m3u8_progress_callback
                )
                
                # Upload to GitHub from temporary file
                await progress_msg.edit("📤 **Uploading to GitHub...**\n⏳ Starting...")
                download_url = await self.upload_to_github_streaming(temp_file.name, filename, file_size, progress_msg)
                
                remaining = len(self.upload_queues.get(user_id, []))
                queue_text = f"\n\n📋 **Queue:** {remaining} files remaining" if remaining > 0 else ""
                
                await progress_msg.edit(
                    f"✅ **M3U8 Video Upload Complete!**\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(file_size)}\n"
                    f"🎬 **Quality:** {selected_quality or 'Auto'}\n"
                    f"🔗 **Download URL:**\n{download_url}{queue_text}"
                )
                
            except Exception as e:
                logger.error(f"Error processing M3U8: {e}")
                await progress_msg.edit(f"❌ **M3U8 Upload Failed**\n\nError: {str(e)}")
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

    async def process_batch_upload(self, upload_item: dict):
        """Process a single batch upload item"""
        event = upload_item['event']
        batch_items = upload_item['batch_items']
        user_id = upload_item['user_id']
        
        progress_msg = await event.respond(f"📋 **Processing Batch Upload...**\n\n⏳ Found {len(batch_items)} items to process")
        
        try:
            successful = 0
            failed = 0
            
            for i, item in enumerate(batch_items, 1):
                try:
                    await progress_msg.edit(
                        f"📋 **Processing Batch Upload...**\n\n"
                        f"📁 Processing: `{item['name']}`\n"
                        f"⏳ Progress: {i}/{len(batch_items)}\n"
                        f"✅ Successful: {successful}\n"
                        f"❌ Failed: {failed}"
                    )
                    
                    # Check if it's an M3U8 URL
                    if await self.m3u8_handler.is_m3u8_url(item['url']):
                        # Add M3U8 item to queue
                        m3u8_item = {
                            'type': 'm3u8',
                            'event': event,
                            'url': item['url'],
                            'filename': item['name'],
                            'user_id': user_id,
                            'quality': None  # Will use default/highest quality
                        }
                        await self.add_to_queue(user_id, m3u8_item)
                    else:
                        # Add regular URL item to queue
                        url_item = {
                            'type': 'url',
                            'event': event,
                            'url': item['url'],
                            'filename': item['name'],
                            'user_id': user_id
                        }
                        await self.add_to_queue(user_id, url_item)
                    
                    successful += 1
                    
                except Exception as e:
                    logger.error(f"Error processing batch item {item['name']}: {e}")
                    failed += 1
            
            remaining = len(self.upload_queues.get(user_id, []))
            await progress_msg.edit(
                f"✅ **Batch Upload Queued!**\n\n"
                f"📊 **Total items:** {len(batch_items)}\n"
                f"✅ **Successfully queued:** {successful}\n"
                f"❌ **Failed:** {failed}\n"
                f"📋 **Items in queue:** {remaining}"
            )
            
        except Exception as e:
            logger.error(f"Error processing batch upload: {e}")
            await progress_msg.edit(f"❌ **Batch Upload Failed**\n\nError: {str(e)}")

    async def start(self):
        """Start the bot"""
        try:
            await self.client.start(bot_token=self.config.telegram_bot_token)
            logger.info("Bot started successfully")
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            raise
        
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            user_id = event.sender_id
            is_admin = self.is_admin(user_id)
            admin_status = "**Admin User**" if is_admin else "**Regular User**"
            
            await event.respond(
                f"🤖 **GitHub Release Uploader Bot**\n\n"
                f"👤 {admin_status}\n\n"
                "Send me files or URLs to upload to GitHub release!\n\n"
                "**Features:**\n"
                "• Send multiple files - they'll upload one by one\n"
                "• Send multiple URLs - processed in order\n"
                "• M3U8 video support with quality selection\n"
                "• Batch upload from text files (format: `name : url`)\n"
                "• Real-time progress with speed display\n"
                "• Queue system for batch uploads\n\n"
                "**Commands:**\n"
                "• Send any file (up to 4GB)\n"
                "• Send a URL to download and upload\n"
                "• Send M3U8 video links (with quality options)\n"
                "• Send .txt file for batch upload\n"
                "• /help - Show this message\n"
                "• /status - Check upload status\n"
                "• /queue - Check queue status\n" +
                ("• /list - List files in release with navigation (Admin only)\n"
                "• /search <filename> - Search files by name (Admin only)\n"
                "• /delete <numbers/ranges> - Delete files (Admin only)\n"
                "• /rename <number> <new_filename> - Rename file (Admin only)\n"
                "• /stop - Stop all processes (Admin only)\n"
                "• /restart - Restart all processes (Admin only)" if is_admin else "")
            )
            raise events.StopPropagation

        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            user_id = event.sender_id
            data = event.data.decode('utf-8')
            
            # Handle quality selection for M3U8
            if data.startswith('quality_'):
                if user_id not in self.pending_quality_selection:
                    await event.answer("Selection expired", alert=True)
                    return
                
                quality = data.split('_', 1)[1]
                pending = self.pending_quality_selection[user_id]
                url = pending['url']
                original_event = pending['event']
                
                # Remove from pending
                del self.pending_quality_selection[user_id]
                
                # Generate filename based on quality
                filename = url.split('/')[-1]
                if '?' in filename:
                    filename = filename.split('?')[0]
                if not filename.endswith('.mp4'):
                    filename = f"video_{quality}_{int(time.time())}.mp4"
                else:
                    name_part = filename.rsplit('.', 1)[0]
                    filename = f"{name_part}_{quality}.mp4"
                
                sanitized_filename = self.sanitize_filename(filename)
                
                # Add to queue with selected quality
                upload_item = {
                    'type': 'm3u8',
                    'event': original_event,
                    'url': url,
                    'filename': sanitized_filename,
                    'user_id': user_id,
                    'quality': quality
                }
                
                queue_position = len(self.upload_queues.get(user_id, [])) + 1
                await event.edit(f"✅ **Quality Selected: {quality}**\n\n📋 **Position in Queue:** {queue_position}")
                
                await self.add_to_queue(user_id, upload_item)
                await event.answer()
                return
            
            # Handle admin functions
            if not self.is_admin(user_id):
                await event.answer("Access denied", alert=True)
                return
            
            if data.startswith('list_page_'):
                page = int(data.split('_')[2])
                await self.send_file_list(event, page, edit=True)
                await event.answer()
            elif data == 'close_list':
                await event.delete()
                await event.answer()

        @self.client.on(events.NewMessage)
        async def message_handler(event):
            # Skip if it's a command (already handled by specific handlers)
            if event.message.text and event.message.text.startswith('/'):
                return
            
            user_id = event.sender_id

            # Check if processes are stopped
            if self.should_stop:
                await event.respond("🛑 **Bot is currently stopped**\n\nPlease wait for an administrator to restart the bot using /restart command.")
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
                        # Check if it's an M3U8 URL (improved detection)
                        if await self.m3u8_handler.is_m3u8_url(text):
                            await self.handle_m3u8_upload(event)
                        else:
                            await self.handle_url_upload(event)
                        return
                    
                    # Only respond to non-empty text that's not a URL or command
                    if text and not text.startswith('/'):
                        await event.respond(
                            "❓ **Invalid Input**\n\n"
                            "Please send:\n"
                            "• A file (drag & drop or attach)\n"
                            "• A direct download URL\n"
                            "• An M3U8 video link\n"
                            "• A .txt file for batch upload (format: `name : url`)\n\n"
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

    async def handle_m3u8_upload(self, event):
        """Handle M3U8 video upload"""
        user_id = event.sender_id
        url = event.message.text.strip()
        
        try:
            # Check for available qualities
            progress_msg = await event.respond("🎬 **Analyzing M3U8 video...**\n⏳ Checking available qualities...")
            
            temp_path, qualities, selected_playlist = await self.m3u8_handler.process_m3u8_url(url)
            
            if qualities:
                # Multiple qualities available - show selection
                quality_buttons = []
                for quality in qualities[:6]:  # Limit to 6 options
                    quality_buttons.append([Button.inline(
                        f"📺 {quality['name']} ({quality['resolution']})",
                        f"quality_{quality['name']}"
                    )])
                
                # Store pending selection
                self.pending_quality_selection[user_id] = {
                    'url': url,
                    'event': event,
                    'qualities': qualities
                }
                
                await progress_msg.edit(
                    "🎬 **M3U8 Video Quality Selection**\n\n"
                    "📺 **Available Qualities:**\n\n" +
                    "\n".join([f"• **{q['name']}** - {q['resolution']}" for q in qualities[:6]]) +
                    "\n\n👆 **Select your preferred quality:**",
                    buttons=quality_buttons
                )
            else:
                # Single quality or direct playlist
                filename = url.split('/')[-1]
                if '?' in filename:
                    filename = filename.split('?')[0]
                if not filename.endswith('.mp4'):
                    filename = f"video_{int(time.time())}.mp4"
                
                sanitized_filename = self.sanitize_filename(filename)
                
                # Add to queue directly
                upload_item = {
                    'type': 'm3u8',
                    'event': event,
                    'url': url,
                    'filename': sanitized_filename,
                    'user_id': user_id,
                    'quality': None
                }
                
                queue_position = len(self.upload_queues.get(user_id, [])) + 1
                await progress_msg.edit(f"📋 **M3U8 Video Queued**\n\n🎬 **Video:** `{sanitized_filename}`\n🔢 **Position:** {queue_position}")
                
                await self.add_to_queue(user_id, upload_item)
                
        except Exception as e:
            logger.error(f"Error handling M3U8 upload: {e}")
            await event.respond(f"❌ **M3U8 Error**\n\nFailed to process M3U8 video: {str(e)}")

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
        
        # Check if it's a batch upload text file
        if filename.lower().endswith('.txt'):
            await self.handle_batch_upload(event)
            return
        
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

    async def handle_batch_upload(self, event):
        """Handle batch upload from text file"""
        user_id = event.sender_id
        document = event.message.document
        
        try:
            progress_msg = await event.respond("📋 **Processing batch file...**\n⏳ Reading file content...")
            
            # Download the text file
            with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as temp_file:
                await self.client.download_media(document, file=temp_file.name)
                
                # Read file content
                with open(temp_file.name, 'r', encoding='utf-8') as f:
                    file_content = f.read()
                
                # Clean up temp file
                os.unlink(temp_file.name)
            
            # Parse batch items
            batch_items = await self.parse_batch_file(file_content)
            
            if not batch_items:
                await progress_msg.edit("❌ **No valid items found**\n\nPlease check your file format:\n`video_name : url`")
                return
            
            # Add batch processing to queue
            upload_item = {
                'type': 'batch',
                'event': event,
                'batch_items': batch_items,
                'user_id': user_id
            }
            
            await progress_msg.edit(f"✅ **Batch file processed**\n\n📊 **Found:** {len(batch_items)} valid items\n⏳ **Adding to queue...**")
            await self.process_batch_upload(upload_item)
            
        except Exception as e:
            logger.error(f"Error handling batch upload: {e}")
            await event.respond(f"❌ **Batch Upload Error**\n\nFailed to process batch file: {str(e)}")

    async def download_telegram_file_streaming(self, document, temp_file, progress_msg, filename: str):
        """Download file from Telegram with progress and speed using streaming to temp file - OPTIMIZED"""
        total_size = document.size
        downloaded = 0
        start_time = time.time()
        last_update_time = start_time
        last_downloaded = 0
        
        async def progress_callback(current, total):
            nonlocal downloaded, last_update_time, last_downloaded
            
            # Check if we should stop
            if self.should_stop:
                raise Exception("Upload stopped by admin command")
            
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
        
        session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        )
        
        # Track this session for potential cancellation
        user_id = getattr(progress_msg, 'sender_id', 0)
        self.add_active_session(user_id, session)
        
        try:
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
                    # Check if we should stop
                    if self.should_stop:
                        raise Exception("Upload stopped by admin command")
                    
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
        finally:
            self.remove_active_session(user_id, session)
            if not session.closed:
                await session.close()

    async def upload_to_github_streaming(self, temp_file_path: str, filename: str, file_size: int, progress_msg) -> str:
        """Upload file to GitHub with progress and speed using streaming"""
        uploaded = 0
        start_time = time.time()
        last_update_time = start_time
        last_uploaded = 0
        
        async def progress_callback(current: int):
            nonlocal uploaded, last_update_time, last_uploaded
            
            # Check if we should stop
            if self.should_stop:
                raise Exception("Upload stopped by admin command")
            
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

    def parse_delete_numbers(self, delete_args: str) -> List[int]:
        """Parse delete command arguments to extract file numbers"""
        numbers = []
        
        # Split by comma to handle multiple arguments
        parts = [part.strip() for part in delete_args.split(',')]
        
        for part in parts:
            if '-' in part and part.count('-') == 1:
                # Handle range (e.g., "1-5")
                try:
                    start, end = part.split('-')
                    start_num = int(start.strip())
                    end_num = int(end.strip())
                    
                    if start_num > end_num:
                        continue  # Invalid range
                    
                    numbers.extend(range(start_num, end_num + 1))
                except ValueError:
                    continue  # Invalid range format
            else:
                # Handle single number
                try:
                    numbers.append(int(part))
                except ValueError:
                    continue  # Invalid number
        
        return numbers

    async def send_file_list(self, event, page=1, edit=False):
        """Send file list with pagination buttons"""
        assets = await self.github_uploader.list_release_assets()
        if not assets:
            if edit:
                await event.edit("📂 **No files found in release**")
            else:
                await event.respond("📂 **No files found in release**")
            return
        
        # Pagination logic
        per_page = 20
        total_pages = (len(assets) + per_page - 1) // per_page
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        page_assets = assets[start_idx:end_idx]
        
        if not page_assets:
            if edit:
                await event.edit(f"📂 **Page {page} not found**\n\nTotal pages: {total_pages}")
            else:
                await event.respond(f"📂 **Page {page} not found**\n\nTotal pages: {total_pages}")
            return
        
        response = f"📂 **Files in Release (Page {page}/{total_pages}):**\n\n"
        
        for i, asset in enumerate(page_assets, start=start_idx + 1):
            size_mb = asset['size'] / (1024 * 1024)
            response += f"**{i}.** `{asset['name']}`\n"
            response += f"   📊 Size: {size_mb:.1f} MB\n"
            response += f"   🔗 [Download]({asset['browser_download_url']})\n\n"
        
        # Add total info
        response += f"📄 **Total:** {len(assets)} files | **Page:** {page}/{total_pages}\n"
        response += f"🗑️ Use `/delete <numbers/ranges>` to delete files\n"
        response += f"✏️ Use `/rename <number> <new_name>` to rename a file"
        
        # Create navigation buttons
        buttons = []
        nav_row = []
        
        # Previous page button
        if page > 1:
            nav_row.append(Button.inline("◀️ Previous", f"list_page_{page-1}"))
        
        # Next page button
        if page < total_pages:
            nav_row.append(Button.inline("Next ▶️", f"list_page_{page+1}"))
        
        if nav_row:
            buttons.append(nav_row)
        
        # Close button
        buttons.append([Button.inline("❌ Close", "close_list")])
        
        if edit:
            await event.edit(response, buttons=buttons)
        else:
            await event.respond(response, buttons=buttons)

async def main():
    bot = TelegramBot()
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())
