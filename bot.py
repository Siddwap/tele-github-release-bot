
import asyncio
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional, BinaryIO, Dict, List
from collections import deque
import aiohttp
from pytubefix import YouTube
from pytubefix.cli import on_progress
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename
from telethon.tl.custom import Button
from dotenv import load_dotenv
from github_uploader import GitHubUploader
from config import BotConfig
import time
import uuid

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
        
        # Generate unique session name to avoid database locks
        session_name = f'bot_{uuid.uuid4().hex[:8]}'
        self.client = TelegramClient(session_name, self.config.telegram_api_id, self.config.telegram_api_hash)
        self.github_uploader = GitHubUploader(self.config.github_token, self.config.github_repo, self.config.github_release_tag)
        self.active_uploads = {}
        self.upload_queues: Dict[int, deque] = {}  # User ID -> queue of uploads
        self.processing_queues: Dict[int, bool] = {}  # User ID -> is processing
        self.should_stop = False  # Flag to control stopping processes
        self.active_sessions: Dict[int, List] = {}  # User ID -> list of active aiohttp sessions
        self.batch_results: Dict[int, List] = {}  # User ID -> list of upload results for batch operations
        self.youtube_pending: Dict[int, Dict] = {}  # User ID -> YouTube video data for quality selection

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

    def sanitize_filename_preserve_unicode(self, filename: str) -> str:
        """Sanitize filename while preserving Unicode characters like Hindi"""
        import re
        
        # Split filename and extension
        if '.' in filename:
            name_part = '.'.join(filename.split('.')[:-1])
            extension = filename.split('.')[-1]
        else:
            name_part = filename
            extension = ''
        
        # Only replace truly problematic characters, preserve Unicode
        # Remove: < > : " | ? * \ / and control characters
        name_part = re.sub(r'[<>:"|?*\\/\x00-\x1f\x7f]', '_', name_part)
        
        # Replace multiple spaces with single space
        name_part = re.sub(r'\s+', ' ', name_part)
        
        # Remove leading/trailing spaces and dots
        name_part = name_part.strip(' .')
        
        # Ensure we have some content
        if not name_part:
            name_part = 'file'
        
        # Reconstruct filename with extension
        if extension:
            return f"{name_part}.{extension}"
        else:
            return name_part

    def sanitize_filename(self, filename: str) -> str:
        """Legacy sanitize method - kept for compatibility"""
        return self.sanitize_filename_preserve_unicode(filename)

    def detect_file_type_from_url(self, url: str) -> str:
        """Detect file type from URL"""
        url_lower = url.lower()
        
        # Remove query parameters for extension detection
        clean_url = url_lower.split('?')[0]
        
        # Video formats
        if any(ext in clean_url for ext in ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm']):
            return 'video'
        elif any(ext in clean_url for ext in ['.m3u8', '.m3u']):
            return 'm3u8'
        # Audio formats
        elif any(ext in clean_url for ext in ['.mp3', '.wav', '.flac', '.aac', '.ogg']):
            return 'audio'
        # Document formats
        elif any(ext in clean_url for ext in ['.pdf', '.doc', '.docx', '.txt', '.rtf']):
            return 'document'
        # Image formats
        elif any(ext in clean_url for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']):
            return 'image'
        # Archive formats
        elif any(ext in clean_url for ext in ['.zip', '.rar', '.7z', '.tar', '.gz']):
            return 'archive'
        else:
            return 'unknown'

    def get_file_extension_from_url(self, url: str) -> str:
        """Extract file extension from URL"""
        clean_url = url.split('?')[0]  # Remove query parameters
        if '.' in clean_url:
            return clean_url.split('.')[-1].lower()
        return ''

    async def parse_txt_file_content(self, content: str) -> List[Dict]:
        """Parse txt file content and extract filename:url pairs"""
        lines = content.strip().split('\n')
        parsed_items = []
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):  # Skip empty lines and comments
                continue
            
            if ':' in line:
                # Split on first colon to handle URLs with colons
                parts = line.split(':', 1)
                if len(parts) == 2:
                    filename = parts[0].strip()
                    url = parts[1].strip()
                    
                    if filename and url:
                        # Detect file type from URL
                        file_type = self.detect_file_type_from_url(url)
                        
                        # If filename doesn't have extension, try to add one from URL
                        if '.' not in filename:
                            ext = self.get_file_extension_from_url(url)
                            if ext:
                                filename = f"{filename}.{ext}"
                        
                        parsed_items.append({
                            'filename': filename,
                            'url': url,
                            'file_type': file_type,
                            'line_number': line_num
                        })
                    else:
                        logger.warning(f"Invalid format on line {line_num}: {line}")
                else:
                    logger.warning(f"Invalid format on line {line_num}: {line}")
            else:
                # Treat as URL only, generate filename
                if line.startswith('http'):
                    url = line
                    filename = url.split('/')[-1] or f"file_{line_num}"
                    if '?' in filename:
                        filename = filename.split('?')[0]
                    
                    file_type = self.detect_file_type_from_url(url)
                    
                    # Add extension if missing
                    if '.' not in filename:
                        ext = self.get_file_extension_from_url(url)
                        if ext:
                            filename = f"{filename}.{ext}"
                        else:
                            filename = f"{filename}.bin"
                    
                    parsed_items.append({
                        'filename': filename,
                        'url': url,
                        'file_type': file_type,
                        'line_number': line_num
                    })
                else:
                    logger.warning(f"Invalid URL on line {line_num}: {line}")
        
        return parsed_items

    async def create_result_txt_file(self, results: List[Dict], original_filename: str) -> str:
        """Create a txt file with the upload results"""
        content_lines = []
        content_lines.append(f"# Upload Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        content_lines.append(f"# Original file: {original_filename}")
        content_lines.append("")
        
        for result in results:
            if result['success']:
                content_lines.append(f"{result['filename']} : {result['github_url']}")
            else:
                content_lines.append(f"# FAILED: {result['filename']} - {result['error']}")
        
        return '\n'.join(content_lines)

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
            total_items = len(self.upload_queues[user_id])
            current_item = 0
            
            while self.upload_queues[user_id] and not self.should_stop:
                current_item += 1
                upload_item = self.upload_queues[user_id].popleft()
                remaining_items = len(self.upload_queues[user_id])
                
                # Get filename safely with fallback
                filename = upload_item.get('filename', upload_item.get('original_filename', 'Unknown File'))
                
                # Update active uploads with current progress
                self.active_uploads[user_id] = {
                    'filename': filename,
                    'status': f"Processing {current_item}/{total_items} - {remaining_items} remaining",
                    'current_item': current_item,
                    'total_items': total_items,
                    'remaining_items': remaining_items
                }
                
                if upload_item['type'] == 'file':
                    await self.process_file_upload(upload_item, current_item, total_items)
                elif upload_item['type'] == 'url':
                    await self.process_url_upload(upload_item, current_item, total_items)
                elif upload_item['type'] == 'txt_batch':
                    await self.process_txt_batch_upload(upload_item)
                
        except Exception as e:
            logger.error(f"Error processing queue for user {user_id}: {e}")
        finally:
            self.processing_queues[user_id] = False
            if user_id in self.active_uploads:
                del self.active_uploads[user_id]

    async def process_file_upload(self, upload_item: dict, current_item: int = 1, total_items: int = 1):
        """Process a single file upload from queue"""
        event = upload_item['event']
        document = upload_item['document']
        filename = upload_item['filename']
        file_size = upload_item['file_size']
        user_id = upload_item['user_id']
        
        remaining = len(self.upload_queues.get(user_id, []))
        
        progress_msg = await event.respond(
            f"📥 **Downloading from Telegram...** ({current_item}/{total_items})\n"
            f"📁 **File:** `{filename}`\n"
            f"📊 **Size:** {self.format_size(file_size)}\n"
            f"📋 **Remaining:** {remaining} files\n"
            f"⏳ Starting..."
        )
        
        # Use temporary file for streaming
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            try:
                # Download file with progress to temporary file
                await self.download_telegram_file_streaming(document, temp_file, progress_msg, filename, current_item, total_items)
                
                # Upload to GitHub from temporary file
                await self.upload_to_github_streaming(temp_file.name, filename, file_size, progress_msg, current_item, total_items)
                
                remaining = len(self.upload_queues.get(user_id, []))
                queue_text = f"\n\n📋 **Queue:** {remaining} files remaining" if remaining > 0 else ""
                
                download_url = f"https://github.com/{self.config.github_repo}/releases/download/{self.config.github_release_tag}/{filename}"
                
                await progress_msg.edit(
                    f"✅ **Upload Complete!** ({current_item}/{total_items})\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}{queue_text}"
                )
                
            except Exception as e:
                logger.error(f"Error uploading file: {e}")
                await progress_msg.edit(f"❌ **Upload Failed** ({current_item}/{total_items})\n\nError: {str(e)}")
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

    async def process_url_upload(self, upload_item: dict, current_item: int = 1, total_items: int = 1):
        """Process a single URL upload from queue"""
        event = upload_item['event']
        url = upload_item['url']
        filename = upload_item['filename']
        user_id = upload_item['user_id']
        
        remaining = len(self.upload_queues.get(user_id, []))
        
        progress_msg = await event.respond(
            f"📥 **Downloading from URL...** ({current_item}/{total_items})\n"
            f"📁 **File:** `{filename}`\n"
            f"🔗 **URL:** `{url[:50]}...`\n"
            f"📋 **Remaining:** {remaining} files\n"
            f"⏳ Starting..."
        )
        
        # Use temporary file for streaming
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            try:
                # Download from URL with progress to temporary file
                file_size = await self.download_from_url_streaming(url, temp_file, progress_msg, filename, current_item, total_items)
                
                # Upload to GitHub from temporary file
                await self.upload_to_github_streaming(temp_file.name, filename, file_size, progress_msg, current_item, total_items)
                
                remaining = len(self.upload_queues.get(user_id, []))
                queue_text = f"\n\n📋 **Queue:** {remaining} files remaining" if remaining > 0 else ""
                
                download_url = f"https://github.com/{self.config.github_repo}/releases/download/{self.config.github_release_tag}/{filename}"
                
                await progress_msg.edit(
                    f"✅ **Upload Complete!** ({current_item}/{total_items})\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}{queue_text}"
                )
                
            except Exception as e:
                logger.error(f"Error processing URL: {e}")
                await progress_msg.edit(f"❌ **Upload Failed** ({current_item}/{total_items})\n\nError: {str(e)}")
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

    async def process_txt_batch_upload(self, upload_item: dict):
        """Process batch upload from txt file"""
        event = upload_item['event']
        txt_items = upload_item['txt_items']
        original_filename = upload_item['original_filename']
        user_id = upload_item['user_id']
        
        total_items = len(txt_items)
        results = []
        
        status_msg = await event.respond(
            f"📋 **Batch Upload Started**\n\n"
            f"📁 **Source:** `{original_filename}`\n"
            f"📊 **Total Items:** {total_items}\n"
            f"⏳ **Status:** Starting..."
        )
        
        for i, item in enumerate(txt_items, 1):
            if self.should_stop:
                break
                
            try:
                remaining = total_items - i
                
                # Download from URL to temporary file
                with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                    try:
                        # Download with individual file progress
                        file_size = await self.download_from_url_streaming_with_progress(
                            item['url'], temp_file, status_msg, item['filename'], i, total_items
                        )
                        
                        # Sanitize filename preserving Unicode
                        sanitized_filename = self.sanitize_filename_preserve_unicode(item['filename'])
                        
                        # Upload to GitHub with individual file progress
                        download_url = await self.upload_to_github_streaming_with_progress(
                            temp_file.name, sanitized_filename, file_size, status_msg, i, total_items
                        )
                        
                        results.append({
                            'filename': sanitized_filename,
                            'original_filename': item['filename'],
                            'github_url': download_url,
                            'success': True,
                            'error': None
                        })
                        
                        logger.info(f"Successfully uploaded {sanitized_filename} ({i}/{total_items})")
                        
                    except Exception as e:
                        logger.error(f"Error uploading {item['filename']}: {e}")
                        results.append({
                            'filename': item['filename'],
                            'original_filename': item['filename'],
                            'github_url': None,
                            'success': False,
                            'error': str(e)
                        })
                    finally:
                        try:
                            os.unlink(temp_file.name)
                        except:
                            pass
                            
            except Exception as e:
                logger.error(f"Error processing item {i}: {e}")
                results.append({
                    'filename': item['filename'],
                    'original_filename': item['filename'],
                    'github_url': None,
                    'success': False,
                    'error': str(e)
                })
        
        # Create result txt file and send it via Telegram
        try:
            result_content = await self.create_result_txt_file(results, original_filename)
            result_filename = f"results_{original_filename.replace('.txt', '')}_{int(time.time())}.txt"
            
            # Create temporary file with results
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False, encoding='utf-8') as result_file:
                result_file.write(result_content)
                result_file.flush()
                
                try:
                    # Count successes and failures
                    successful = sum(1 for r in results if r['success'])
                    failed = total_items - successful
                    
                    # Send the result file via Telegram
                    await event.client.send_file(
                        event.chat_id,
                        result_file.name,
                        caption=(
                            f"✅ **Batch Upload Complete!**\n\n"
                            f"📁 **Source:** `{original_filename}`\n"
                            f"📊 **Total:** {total_items} items\n"
                            f"✅ **Successful:** {successful}\n"
                            f"❌ **Failed:** {failed}\n\n"
                            f"📄 **Results file attached above** ⬆️"
                        ),
                        attributes=[DocumentAttributeFilename(result_filename)]
                    )
                    
                    await status_msg.delete()
                    
                except Exception as e:
                    logger.error(f"Error sending result file: {e}")
                    await status_msg.edit(
                        f"⚠️ **Batch Upload Complete with Issues**\n\n"
                        f"📁 **Source:** `{original_filename}`\n"
                        f"📊 **Processed:** {len(results)}/{total_items}\n"
                        f"❌ **Could not send results file:** {str(e)}"
                    )
                finally:
                    try:
                        os.unlink(result_file.name)
                    except:
                        pass
                        
        except Exception as e:
            logger.error(f"Error creating result file: {e}")
            successful = sum(1 for r in results if r['success'])
            failed = total_items - successful
            
            await status_msg.edit(
                f"⚠️ **Batch Upload Complete**\n\n"
                f"📁 **Source:** `{original_filename}`\n"
                f"📊 **Total:** {total_items} items\n"
                f"✅ **Successful:** {successful}\n"
                f"❌ **Failed:** {failed}\n\n"
                f"⚠️ **Could not generate results file**"
            )

    async def download_from_url_streaming_with_progress(self, url: str, temp_file, progress_msg, filename: str, current_item: int, total_items: int) -> int:
        """Download file from URL with individual progress tracking"""
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
                
                chunk_size = 8 * 1024 * 1024  # 8MB chunks
                
                async for chunk in response.content.iter_chunked(chunk_size):
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
                        if progress - getattr(self, f'_last_batch_dl_progress_{current_item}', 0) >= 2 or time_diff >= 2:
                            remaining = total_items - current_item
                            await progress_msg.edit(
                                f"📥 **Downloading...** ({current_item}/{total_items})\n\n"
                                f"📁 **Current:** `{filename}`\n"
                                f"📊 **Size:** {self.format_size(downloaded)} / {self.format_size(total_size)}\n"
                                f"⏳ **Progress:** {progress:.1f}%\n"
                                f"🚀 **Speed:** {self.format_size(speed)}/s\n"
                                f"📋 **Remaining:** {remaining} files\n"
                                f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
                            )
                            setattr(self, f'_last_batch_dl_progress_{current_item}', progress)
                            last_update_time = current_time
                            last_downloaded = downloaded
                
                temp_file.flush()
                return downloaded
        finally:
            self.remove_active_session(user_id, session)
            if not session.closed:
                await session.close()

    async def upload_to_github_streaming_with_progress(self, temp_file_path: str, filename: str, file_size: int, progress_msg, current_item: int, total_items: int) -> str:
        """Upload file to GitHub with individual progress tracking"""
        uploaded = 0
        start_time = time.time()
        last_update_time = start_time
        last_uploaded = 0
        
        async def progress_callback(current: int):
            nonlocal uploaded, last_update_time, last_uploaded
            
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
            if progress - getattr(progress_callback, f'last_progress_{current_item}', 0) >= 2 or time_diff >= 2:
                remaining = total_items - current_item
                await progress_msg.edit(
                    f"📤 **Uploading to GitHub...** ({current_item}/{total_items})\n\n"
                    f"📁 **Current:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(current)} / {self.format_size(file_size)}\n"
                    f"⏳ **Progress:** {progress:.1f}%\n"
                    f"🚀 **Speed:** {self.format_size(speed)}/s\n"
                    f"📋 **Remaining:** {remaining} files\n"
                    f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
                )
                setattr(progress_callback, f'last_progress_{current_item}', progress)
                last_update_time = current_time
                last_uploaded = current
        
        return await self.github_uploader.upload_asset_streaming(temp_file_path, filename, file_size, progress_callback)

    async def download_from_url_streaming_silent(self, url: str, temp_file) -> int:
        """Download file from URL silently (no progress updates)"""
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
        
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download: HTTP {response.status}")
                
                downloaded = 0
                chunk_size = 8 * 1024 * 1024  # 8MB chunks
                
                async for chunk in response.content.iter_chunked(chunk_size):
                    if self.should_stop:
                        raise Exception("Upload stopped by admin command")
                    
                    temp_file.write(chunk)
                    downloaded += len(chunk)
                
                temp_file.flush()
                return downloaded
        finally:
            if not session.closed:
                await session.close()

    async def upload_to_github_streaming_silent(self, temp_file_path: str, filename: str, file_size: int) -> str:
        """Upload file to GitHub silently (no progress updates)"""
        return await self.github_uploader.upload_asset_streaming(temp_file_path, filename, file_size, None)

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
                "• Send YouTube URLs - choose quality and auto-merge\n"
                "• Send TXT files with filename:url format for batch upload\n"
                "• Real-time progress with speed display\n"
                "• Queue system for batch uploads\n"
                "• Preserves Unicode filenames (Hindi, etc.)\n\n"
                "**Commands:**\n"
                "• Send any file (up to 4GB)\n"
                "• Send a URL to download and upload\n"
                "• Send YouTube URL for video download\n"
                "• Send TXT file with filename:url pairs\n"
                "• /help - Show this message\n"
                "• /status - Check upload status\n"
                "• /queue - Check queue status\n" +
                ("• /list - List files in release with navigation (Admin only)\n"
                "• /search <filename> - Search files by name (Admin only)\n"
                "• /delete <number> - Delete file by list number (Admin only)\n"
                "• /rename <number> <new_filename> - Rename file (Admin only)\n"
                "• /stop - Stop all processes (Admin only)\n"
                "• /restart - Restart all processes (Admin only)" if is_admin else "")
            )
            raise events.StopPropagation

        # ... keep existing code (all event handlers for help, stop, restart, status, queue, list, search, delete, rename, callbacks, etc.)

        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            user_id = event.sender_id
            is_admin = self.is_admin(user_id)
            
            basic_help = (
                "**How to use:**\n\n"
                "1. **File Upload**: Send any file directly to the bot\n"
                "2. **URL Upload**: Send a URL pointing to a file\n"
                "3. **YouTube Download**: Send a YouTube URL, select quality, and bot will merge & upload\n"
                "4. **Batch Upload**: Send TXT file with filename:url pairs\n"
                "5. **Queue System**: Send multiple files/URLs - they'll queue automatically\n\n"
                "**YouTube Support:**\n"
                "• Send any YouTube video URL\n"
                "• Bot fetches available qualities (360p, 720p, 1080p, 2K, 4K)\n"
                "• Select your preferred quality\n"
                "• Bot automatically merges audio+video using FFmpeg\n"
                "• Uploads final video to GitHub release\n\n"
                "**TXT File Format for Batch Upload:**\n"
                "```\n"
                "movie1.mp4 : https://example.com/video1.mp4\n"
                "document.pdf : https://example.com/doc.pdf\n"
                "song.mp3 : https://example.com/audio.mp3\n"
                "```\n\n"
                "**Features:**\n"
                "• Supports files up to 4GB\n"
                "• Real-time progress updates with speed\n"
                "• Queue system for multiple uploads\n"
                "• Direct upload to GitHub releases\n"
                "• Preserves Unicode filenames (Hindi, Arabic, etc.)\n"
                "• Batch upload generates results TXT file\n"
                "• YouTube video download with quality selection\n\n"
                f"**Target Repository:** `{self.config.github_repo}`\n"
                f"**Release Tag:** `{self.config.github_release_tag}`"
            )
            
            admin_help = (
                "\n\n**Admin Commands:**\n"
                "• /list - Browse files with navigation buttons\n"
                "• /search <filename> - Search files by name\n"
                "• /delete <number> - Remove file by list number\n"
                "• /rename <number> <new_name> - Rename file by list number\n"
                "• /stop - Stop all running processes\n"
                "• /restart - Restart all processes\n\n"
                "**Examples:**\n"
                "• /list - Browse files with Previous/Next buttons\n"
                "• /search video.mp4 - Find files containing 'video.mp4'\n"
                "• /delete 5 - Delete file number 5 from list\n"
                "• /rename 5 new_video.mp4 - Rename file number 5"
            )
            
            help_text = basic_help + (admin_help if is_admin else "")
            await event.respond(help_text)
            raise events.StopPropagation

        @self.client.on(events.NewMessage(pattern='/stop'))
        async def stop_handler(event):
            user_id = event.sender_id
            if not self.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            await self.stop_all_processes()
            await event.respond("🛑 **All processes stopped**\n\nAll uploads, queues, and active processes have been halted.\n\nUse /restart to resume operations.")
            raise events.StopPropagation

        @self.client.on(events.NewMessage(pattern='/restart'))
        async def restart_handler(event):
            user_id = event.sender_id
            if not self.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            await self.restart_all_processes()
            await event.respond("✅ **Bot restarted successfully**\n\nAll processes are now running normally.")
            raise events.StopPropagation

        @self.client.on(events.NewMessage(pattern='/status'))
        async def status_handler(event):
            user_id = event.sender_id
            if user_id in self.active_uploads:
                upload_info = self.active_uploads[user_id]
                current = upload_info.get('current_item', 1)
                total = upload_info.get('total_items', 1)
                remaining = upload_info.get('remaining_items', 0)
                
                await event.respond(
                    f"📊 **Upload Status**\n\n"
                    f"📁 **Current File:** `{upload_info['filename']}`\n"
                    f"📋 **Progress:** {current}/{total}\n"
                    f"⏳ **Remaining:** {remaining} files\n"
                    f"🔄 **Status:** {upload_info['status']}"
                )
            else:
                await event.respond("📊 **No active uploads**")
            raise events.StopPropagation

        @self.client.on(events.NewMessage(pattern='/queue'))
        async def queue_handler(event):
            user_id = event.sender_id
            if user_id in self.upload_queues and self.upload_queues[user_id]:
                queue_count = len(self.upload_queues[user_id])
                queue_items = []
                for i, item in enumerate(list(self.upload_queues[user_id])[:5]):  # Show first 5
                    filename = item.get('filename', item.get('original_filename', 'Unknown File'))
                    queue_items.append(f"{i+1}. {filename}")
                
                queue_text = "\n".join(queue_items)
                if queue_count > 5:
                    queue_text += f"\n... and {queue_count - 5} more"
                
                await event.respond(f"📋 **Upload Queue ({queue_count} items):**\n\n{queue_text}")
            else:
                await event.respond("📋 Queue is empty")
            raise events.StopPropagation

        @self.client.on(events.NewMessage(pattern='/list'))
        async def list_handler(event):
            user_id = event.sender_id
            if not self.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            try:
                await send_file_list(event, page=1)
            except Exception as e:
                await event.respond(f"❌ **Error listing files**\n\n{str(e)}")
            raise events.StopPropagation

        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            user_id = event.sender_id
            data = event.data.decode('utf-8')
            
            # Handle YouTube quality selection
            if data.startswith('yt_quality_'):
                parts = data.split('_')
                quality = int(parts[2])
                callback_user_id = int(parts[3])
                
                if user_id != callback_user_id:
                    await event.answer("This button is not for you", alert=True)
                    return
                
                if user_id not in self.youtube_pending:
                    await event.answer("Session expired, please send the YouTube URL again", alert=True)
                    return
                
                youtube_data = self.youtube_pending[user_id]
                await event.delete()
                await event.answer()
                
                # Process YouTube download
                await self.process_youtube_upload(
                    youtube_data['event'],
                    youtube_data['url'],
                    quality,
                    youtube_data['data']
                )
                
                # Clean up
                del self.youtube_pending[user_id]
                return
            
            elif data.startswith('yt_cancel_'):
                callback_user_id = int(data.split('_')[2])
                
                if user_id != callback_user_id:
                    await event.answer("This button is not for you", alert=True)
                    return
                
                if user_id in self.youtube_pending:
                    del self.youtube_pending[user_id]
                
                await event.delete()
                await event.answer("❌ Cancelled")
                return
            
            # Handle file list pagination (admin only)
            if not self.is_admin(user_id):
                await event.answer("Access denied", alert=True)
                return
            
            if data.startswith('list_page_'):
                page = int(data.split('_')[2])
                await send_file_list(event, page, edit=True)
                await event.answer()
            elif data == 'close_list':
                await event.delete()
                await event.answer()

        async def send_file_list(event, page=1, edit=False):
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
            response += f"🗑️ Use `/delete <number>` to delete a file\n"
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

        # Store the method in the class for access in callback handler
        self.send_file_list = send_file_list

        @self.client.on(events.NewMessage(pattern=r'/search (.+)'))
        async def search_handler(event):
            user_id = event.sender_id
            if not self.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            try:
                search_term = event.pattern_match.group(1).strip().lower()
                if not search_term:
                    await event.respond("❌ **Usage:** /search <filename>")
                    return
                
                assets = await self.github_uploader.list_release_assets()
                if not assets:
                    await event.respond("📂 **No files found in release**")
                    return
                
                # Filter assets by search term
                matching_assets = []
                for i, asset in enumerate(assets, 1):
                    if search_term in asset['name'].lower():
                        matching_assets.append((i, asset))
                
                if not matching_assets:
                    await event.respond(f"🔍 **No files found matching:** `{search_term}`")
                    return
                
                response = f"🔍 **Search Results for:** `{search_term}`\n\n"
                
                for original_num, asset in matching_assets[:20]:  # Limit to 20 results
                    size_mb = asset['size'] / (1024 * 1024)
                    response += f"**{original_num}.** `{asset['name']}`\n"
                    response += f"   📊 Size: {size_mb:.1f} MB\n"
                    response += f"   🔗 [Download]({asset['browser_download_url']})\n\n"
                
                if len(matching_assets) > 20:
                    response += f"... and {len(matching_assets) - 20} more results\n\n"
                
                response += f"📊 **Found:** {len(matching_assets)} files\n"
                response += f"🗑️ Use `/delete <number>` to delete a file"
                
                await event.respond(response)
                
            except Exception as e:
                await event.respond(f"❌ **Error searching files**\n\n{str(e)}")
            raise events.StopPropagation

        @self.client.on(events.NewMessage(pattern=r'/delete (\d+)'))
        async def delete_handler(event):
            user_id = event.sender_id
            if not self.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            try:
                file_number = int(event.pattern_match.group(1))
                if file_number < 1:
                    await event.respond("❌ **Invalid file number**\n\nFile numbers start from 1")
                    return
                
                assets = await self.github_uploader.list_release_assets()
                if not assets:
                    await event.respond("📂 **No files found in release**")
                    return
                
                if file_number > len(assets):
                    await event.respond(f"❌ **File number {file_number} not found**\n\nTotal files: {len(assets)}")
                    return
                
                # Get the asset to delete (subtract 1 for 0-based indexing)
                target_asset = assets[file_number - 1]
                filename = target_asset['name']
                
                success = await self.github_uploader.delete_asset_by_name(filename)
                if success:
                    await event.respond(
                        f"✅ **File deleted successfully**\n\n"
                        f"🗑️ **File #{file_number}:** `{filename}`"
                    )
                else:
                    await event.respond(f"❌ **Failed to delete file**\n\n📁 **File:** `{filename}`")
                    
            except ValueError:
                await event.respond("❌ **Invalid file number**\n\nPlease provide a valid number")
            except Exception as e:
                await event.respond(f"❌ **Error deleting file**\n\n{str(e)}")
            raise events.StopPropagation

        @self.client.on(events.NewMessage(pattern=r'/rename (\d+) (.+)'))
        async def rename_handler(event):
            user_id = event.sender_id
            if not self.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            try:
                file_number = int(event.pattern_match.group(1))
                new_filename = event.pattern_match.group(2).strip()
                
                if file_number < 1:
                    await event.respond("❌ **Invalid file number**\n\nFile numbers start from 1")
                    return
                
                if not new_filename:
                    await event.respond("❌ **Invalid filename**\n\nPlease provide a valid new filename")
                    return
                
                # Sanitize the new filename while preserving Unicode
                sanitized_filename = self.sanitize_filename_preserve_unicode(new_filename)
                if sanitized_filename != new_filename:
                    await event.respond(f"ℹ️ **Filename sanitized:** `{new_filename}` -> `{sanitized_filename}`")
                
                assets = await self.github_uploader.list_release_assets()
                if not assets:
                    await event.respond("📂 **No files found in release**")
                    return
                
                if file_number > len(assets):
                    await event.respond(f"❌ **File number {file_number} not found**\n\nTotal files: {len(assets)}")
                    return
                
                # Get the asset to rename (subtract 1 for 0-based indexing)
                target_asset = assets[file_number - 1]
                old_filename = target_asset['name']
                
                # Check if new filename already exists
                for asset in assets:
                    if asset['name'] == sanitized_filename:
                        await event.respond(f"❌ **Filename already exists**\n\n📁 **File:** `{sanitized_filename}`")
                        return
                
                progress_msg = await event.respond(f"🔄 **Renaming file...**\n\n📁 **From:** `{old_filename}`\n📁 **To:** `{sanitized_filename}`")
                
                success = await self.github_uploader.rename_asset(old_filename, sanitized_filename)
                if success:
                    await progress_msg.edit(
                        f"✅ **File renamed successfully**\n\n"
                        f"📁 **File #{file_number}**\n"
                        f"🔄 **From:** `{old_filename}`\n"
                        f"🔄 **To:** `{sanitized_filename}`"
                    )
                else:
                    await progress_msg.edit(f"❌ **Failed to rename file**\n\n📁 **File:** `{old_filename}`")
                    
            except ValueError:
                await event.respond("❌ **Invalid command format**\n\nUsage: /rename <number> <new_filename>")
            except Exception as e:
                await event.respond(f"❌ **Error renaming file**\n\n{str(e)}")
            raise events.StopPropagation

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
                    
                    # Check if it's a YouTube URL
                    if self.is_youtube_url(text):
                        await self.handle_youtube_url(event, text)
                        return
                    
                    # Check if it's a regular URL
                    if self.is_url(text):
                        await self.handle_url_upload(event)
                        return
                    
                    # Only respond to non-empty text that's not a URL or command
                    if text and not text.startswith('/'):
                        await event.respond(
                            "❓ **Invalid Input**\n\n"
                            "Please send:\n"
                            "• A file (drag & drop or attach)\n"
                            "• A direct download URL\n"
                            "• A YouTube URL\n"
                            "• A TXT file with filename:url pairs for batch upload\n\n"
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
        finally:
            # Clean up session files on shutdown
            await self.cleanup_session_files()

    async def cleanup_session_files(self):
        """Clean up old session files"""
        try:
            for file in os.listdir('.'):
                if file.startswith('bot_') and (file.endswith('.session') or file.endswith('.session-journal')):
                    try:
                        os.remove(file)
                        logger.info(f"Cleaned up session file: {file}")
                    except Exception as e:
                        logger.warning(f"Could not remove session file {file}: {e}")
        except Exception as e:
            logger.warning(f"Error during session cleanup: {e}")

    def is_url(self, text: str) -> bool:
        """Check if text is a valid URL"""
        if not text:
            return False
        return text.startswith(('http://', 'https://')) and len(text) > 8
    
    def is_youtube_url(self, text: str) -> bool:
        """Check if text is a YouTube URL"""
        if not text:
            return False
        youtube_patterns = [
            'youtube.com/watch',
            'youtu.be/',
            'm.youtube.com/watch',
            'youtube.com/shorts'
        ]
        return any(pattern in text.lower() for pattern in youtube_patterns)
    
    async def fetch_youtube_video_data(self, youtube_url: str) -> Optional[Dict]:
        """Fetch YouTube video data from API"""
        try:
            api_url = f"https://ytdl.testingsd9.workers.dev/?url={youtube_url}"
            
            timeout = aiohttp.ClientTimeout(total=60, connect=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(api_url) as response:
                    if response.status != 200:
                        logger.error(f"API returned status {response.status}")
                        return None
                    
                    data = await response.json()
                    return data
        except Exception as e:
            logger.error(f"Error fetching YouTube data: {e}")
            return None
    
    async def merge_video_audio_ffmpeg(self, video_path: str, audio_path: str, output_path: str, progress_msg=None) -> bool:
        """Merge video and audio using FFmpeg"""
        try:
            if progress_msg:
                await progress_msg.edit("🔄 **Merging video and audio...**\n⏳ Please wait...")
            
            # Run FFmpeg to merge video and audio
            process = await asyncio.create_subprocess_exec(
                'ffmpeg', '-i', video_path, '-i', audio_path,
                '-c:v', 'copy', '-c:a', 'aac', '-strict', 'experimental',
                output_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Successfully merged video and audio to {output_path}")
                return True
            else:
                logger.error(f"FFmpeg error: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Error merging video and audio: {e}")
            return False
    
    async def download_youtube_with_pytubefix(self, youtube_url: str, quality: int, filename: str, progress_msg) -> Optional[str]:
        """Download YouTube video using pytubefix - Currently working method"""
        output_path = None
        
        try:
            await progress_msg.edit(
                f"📥 **Downloading video from YouTube...**\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Quality:** {quality}p\n"
                f"⏳ Initializing..."
            )
            
            logger.info(f"Starting YouTube download with quality: {quality}p")
            logger.info(f"URL: {youtube_url}")
            
            # Initialize YouTube object with pytubefix using WEB client
            # WEB client automatically generates PO tokens to bypass bot detection
            yt = YouTube(
                youtube_url,
                'WEB',  # Use WEB client for automatic PO token generation
                on_progress_callback=on_progress,
                use_oauth=False,
                allow_oauth_cache=False
            )
            
            logger.info(f"Video title: {yt.title}")
            logger.info(f"Video length: {yt.length} seconds")
            
            await progress_msg.edit(
                f"📥 **Downloading video from YouTube...**\n"
                f"📁 **File:** `{filename}`\n"
                f"🎬 **Title:** {yt.title[:50]}...\n"
                f"📊 **Quality:** {quality}p\n"
                f"⏳ Selecting best stream..."
            )
            
            # Get progressive stream (already merged video+audio) at desired quality
            # Progressive streams are simpler and more reliable
            stream = None
            
            # Try to get progressive stream at exact quality
            stream = yt.streams.filter(progressive=True, file_extension='mp4', res=f'{quality}p').first()
            
            # If not available, try adaptive stream (video only) and merge later
            if not stream:
                logger.info(f"No progressive stream at {quality}p, trying adaptive...")
                stream = yt.streams.filter(adaptive=True, file_extension='mp4', res=f'{quality}p').first()
            
            # Fallback to highest quality progressive stream
            if not stream:
                logger.info(f"No stream at {quality}p, getting highest quality progressive...")
                stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
            
            # Last resort: get any mp4 stream
            if not stream:
                logger.info("Getting any available mp4 stream...")
                stream = yt.streams.filter(file_extension='mp4').first()
            
            if not stream:
                raise Exception("No suitable video stream found")
            
            logger.info(f"Selected stream: {stream.resolution} - {stream.mime_type} - Progressive: {stream.is_progressive}")
            
            await progress_msg.edit(
                f"📥 **Downloading video from YouTube...**\n"
                f"📁 **File:** `{filename}`\n"
                f"🎬 **Title:** {yt.title[:50]}...\n"
                f"📊 **Quality:** {stream.resolution}\n"
                f"⏳ Downloading..."
            )
            
            # Create temp directory for download
            temp_dir = tempfile.mkdtemp()
            
            # Download the stream
            output_path = stream.download(output_path=temp_dir, filename='video.mp4')
            
            logger.info(f"Downloaded to: {output_path}")
            
            # Verify file exists and has content
            if not os.path.exists(output_path):
                raise Exception("Download failed - output file not created")
            
            file_size = os.path.getsize(output_path)
            logger.info(f"Downloaded file size: {self.format_size(file_size)}")
            
            if file_size == 0:
                raise Exception("Downloaded file is empty (0 bytes)")
            
            await progress_msg.edit(
                f"✅ **Download complete!**\n"
                f"📁 **File:** `{filename}`\n"
                f"🎬 **Title:** {yt.title[:50]}...\n"
                f"📊 **Size:** {self.format_size(file_size)}\n"
                f"📊 **Quality:** {stream.resolution}\n"
                f"⏳ Preparing for upload..."
            )
            
            return output_path
            
        except Exception as e:
            logger.error(f"Error downloading YouTube video: {e}")
            # Clean up temp file on error
            if output_path and os.path.exists(output_path):
                try:
                    os.unlink(output_path)
                except:
                    pass
            raise e
    
    async def process_youtube_upload(self, event, youtube_url: str, quality: int, video_data: Dict):
        """Process YouTube video download and upload"""
        user_id = event.sender_id
        
        try:
            # Generate filename
            title = video_data.get('text', 'YouTube Video')
            # Sanitize title for filename
            safe_title = self.sanitize_filename_preserve_unicode(title)
            filename = f"{safe_title}_{quality}p.mp4"
            
            progress_msg = await event.respond(
                f"🎬 **Processing YouTube Video**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Quality:** {quality}p\n"
                f"⏳ **Status:** Starting download..."
            )
            
            # Use pytubefix for reliable YouTube downloads
            merged_file_path = await self.download_youtube_with_pytubefix(
                youtube_url,
                quality,
                filename,
                progress_msg
            )
            
            # Get file size
            file_size = os.path.getsize(merged_file_path)
            
            # Upload to GitHub
            await progress_msg.edit(
                f"📤 **Uploading to GitHub...**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Size:** {self.format_size(file_size)}\n"
                f"⏳ **Status:** Uploading..."
            )
            
            await self.upload_to_github_streaming(merged_file_path, filename, file_size, progress_msg, 1, 1)
            
            download_url = f"https://github.com/{self.config.github_repo}/releases/download/{self.config.github_release_tag}/{filename}"
            
            await progress_msg.edit(
                f"✅ **YouTube Upload Complete!**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Size:** {self.format_size(file_size)}\n"
                f"📊 **Quality:** {quality}p\n"
                f"🔗 **Download URL:**\n{download_url}"
            )
            
            # Clean up merged file
            try:
                os.unlink(merged_file_path)
            except:
                pass
                
        except Exception as e:
            logger.error(f"Error processing YouTube upload: {e}")
            await event.respond(f"❌ **YouTube Upload Failed**\n\nError: {str(e)}")

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
        
        file_size = document.size
        logger.info(f"Received file: {filename}, size: {file_size} bytes")
        
        # Check file size (4GB limit)
        if file_size > 4 * 1024 * 1024 * 1024:
            await event.respond("❌ File too large. Maximum size is 4GB.")
            return

        # Check if it's a TXT file for batch upload
        if filename.lower().endswith('.txt'):
            await self.handle_txt_file_upload(event, document, filename)
            return

        # Sanitize filename preserving Unicode
        sanitized_filename = self.sanitize_filename_preserve_unicode(filename)
        if sanitized_filename != filename:
            logger.info(f"Sanitized filename: '{filename}' -> '{sanitized_filename}'")

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

    async def handle_txt_file_upload(self, event, document, filename):
        """Handle TXT file upload for batch processing"""
        user_id = event.sender_id
        
        progress_msg = await event.respond("📄 **Processing TXT file...**\n⏳ Downloading and parsing...")
        
        try:
            # Download TXT file content
            with tempfile.NamedTemporaryFile(mode='w+b', delete=False) as temp_file:
                await self.client.download_media(document, file=temp_file)
                temp_file.flush()
                
                # Read and parse content
                with open(temp_file.name, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
            
            # Parse TXT content
            txt_items = await self.parse_txt_file_content(content)
            
            if not txt_items:
                await progress_msg.edit("❌ **No valid items found in TXT file**\n\nExpected format:\n`filename.ext : https://example.com/file.ext`")
                return
            
            await progress_msg.edit(
                f"✅ **TXT file parsed successfully**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Items found:** {len(txt_items)}\n"
                f"⏳ **Starting batch upload...**"
            )
            
            # Add batch upload to queue
            upload_item = {
                'type': 'txt_batch',
                'event': event,
                'txt_items': txt_items,
                'original_filename': filename,
                'user_id': user_id
            }
            
            await self.add_to_queue(user_id, upload_item)
            
        except Exception as e:
            logger.error(f"Error processing TXT file: {e}")
            await progress_msg.edit(f"❌ **Error processing TXT file**\n\n{str(e)}")

    async def handle_url_upload(self, event):
        """Handle URL upload by adding to queue"""
        user_id = event.sender_id
        url = event.message.text.strip()
        
        # Extract filename from URL
        filename = url.split('/')[-1] or f"download_{int(time.time())}"
        if '?' in filename:
            filename = filename.split('?')[0]
        
        # Detect file type and add appropriate extension if missing
        file_type = self.detect_file_type_from_url(url)
        if '.' not in filename:
            ext = self.get_file_extension_from_url(url)
            if ext:
                filename = f"{filename}.{ext}"
            else:
                filename = f"{filename}.bin"
        
        # Sanitize filename preserving Unicode
        sanitized_filename = self.sanitize_filename_preserve_unicode(filename)
        if sanitized_filename != filename:
            logger.info(f"Sanitized filename: '{filename}' -> '{sanitized_filename}'")
        
        logger.info(f"Queuing URL: {url}, detected type: {file_type}")
        
        # Add to queue
        upload_item = {
            'type': 'url',
            'event': event,
            'url': url,
            'filename': sanitized_filename,
            'user_id': user_id
        }
        
        queue_position = len(self.upload_queues.get(user_id, [])) + 1
        await event.respond(f"📋 **URL Queued**\n\n🔗 **URL:** `{url}`\n📁 **File:** `{sanitized_filename}`\n📋 **Type:** `{file_type}`\n🔢 **Position:** {queue_position}")
        
        await self.add_to_queue(user_id, upload_item)
    
    async def handle_youtube_url(self, event, youtube_url: str):
        """Handle YouTube URL - fetch video data and show quality options"""
        user_id = event.sender_id
        
        progress_msg = await event.respond(
            "🎬 **Fetching YouTube video data...**\n"
            "⏳ Please wait..."
        )
        
        try:
            # Fetch video data from API
            video_data = await self.fetch_youtube_video_data(youtube_url)
            
            if not video_data or 'medias' not in video_data or not video_data['medias']:
                await progress_msg.edit("❌ **Failed to fetch video data**\n\nPlease check the URL and try again.")
                return
            
            if not video_data['medias'][0].get('formats'):
                await progress_msg.edit("❌ **No suitable video formats found**\n\nPlease try a different video or use a direct download link.")
                return
            
            # Get video title and formats
            title = video_data.get('text', 'YouTube Video')
            formats = video_data['medias'][0]['formats']
            
            # Create quality selection buttons
            buttons = []
            for fmt in formats:
                quality = fmt['quality']
                quality_note = fmt['quality_note']
                video_size = fmt.get('video_size', 0)
                audio_size = fmt.get('audio_size', 0)
                total_size = video_size + audio_size
                size_mb = total_size / (1024 * 1024)
                
                button_text = f"{quality_note} ({quality}p) - {size_mb:.1f} MB"
                callback_data = f"yt_quality_{quality}_{user_id}"
                buttons.append([Button.inline(button_text, callback_data)])
            
            # Add cancel button
            buttons.append([Button.inline("❌ Cancel", f"yt_cancel_{user_id}")])
            
            # Store video data for later use
            self.youtube_pending[user_id] = {
                'url': youtube_url,
                'data': video_data,
                'event': event
            }
            
            await progress_msg.edit(
                f"🎬 **YouTube Video Found**\n\n"
                f"📹 **Title:** {title[:100]}{'...' if len(title) > 100 else ''}\n\n"
                f"**Select Quality:**",
                buttons=buttons
            )
            
        except Exception as e:
            logger.error(f"Error handling YouTube URL: {e}")
            await progress_msg.edit(f"❌ **Error processing YouTube URL**\n\n{str(e)}")

    async def download_telegram_file_streaming(self, document, temp_file, progress_msg, filename: str, current_item: int = 1, total_items: int = 1):
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
                remaining = len(self.upload_queues.get(getattr(progress_msg, 'sender_id', 0), []))
                await progress_msg.edit(
                    f"📥 **Downloading from Telegram...** ({current_item}/{total_items})\n\n"
                    f"📁 {filename}\n"
                    f"📊 {self.format_size(current)} / {self.format_size(total)}\n"
                    f"⏳ {progress:.1f}%\n"
                    f"🚀 Speed: {self.format_size(speed)}/s\n"
                    f"📋 Remaining: {remaining} files\n"
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

    async def download_from_url_streaming(self, url: str, temp_file, progress_msg, filename: str, current_item: int = 1, total_items: int = 1) -> int:
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
                            remaining = len(self.upload_queues.get(user_id, []))
                            await progress_msg.edit(
                                f"📥 **Downloading from URL...** ({current_item}/{total_items})\n\n"
                                f"📁 {filename}\n"
                                f"📊 {self.format_size(downloaded)} / {self.format_size(total_size)}\n"
                                f"⏳ {progress:.1f}%\n"
                                f"🚀 Speed: {self.format_size(speed)}/s\n"
                                f"📋 Remaining: {remaining} files\n"
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

    async def upload_to_github_streaming(self, temp_file_path: str, filename: str, file_size: int, progress_msg, current_item: int = 1, total_items: int = 1) -> str:
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
                user_id = getattr(progress_msg, 'sender_id', 0)
                remaining = len(self.upload_queues.get(user_id, []))
                await progress_msg.edit(
                    f"📤 **Uploading to GitHub...** ({current_item}/{total_items})\n\n"
                    f"📁 {filename}\n"
                    f"📊 {self.format_size(current)} / {self.format_size(file_size)}\n"
                    f"⏳ {progress:.1f}%\n"
                    f"🚀 Speed: {self.format_size(speed)}/s\n"
                    f"📋 Remaining: {remaining} files\n"
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
