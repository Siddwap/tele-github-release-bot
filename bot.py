
import asyncio
import logging
import os
import tempfile
import subprocess
import re
from datetime import datetime
from typing import Optional, BinaryIO, Dict, List
from collections import deque
import aiohttp
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename
from telethon.tl.custom import Button
from telethon.errors import FloodWaitError
from dotenv import load_dotenv
from github_uploader import GitHubUploader
from config import BotConfig
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
        self.active_uploads = {}
        self.upload_queues: Dict[int, deque] = {}  # User ID -> queue of uploads
        self.processing_queues: Dict[int, bool] = {}  # User ID -> is processing
        self.should_stop = False  # Flag to control stopping processes
        self.active_sessions: Dict[int, List] = {}  # User ID -> list of active aiohttp sessions
        self.flood_wait_delay = 1  # Initial delay between operations to avoid flood wait
        self.pending_txt_uploads: Dict[int, Dict] = {}  # User ID -> pending TXT upload data
        self.pending_course_name: Dict[int, Dict] = {}  # User ID -> pending course name data

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
        
        # Clear pending TXT uploads
        self.pending_txt_uploads.clear()
        
        # Clear pending course name data
        self.pending_course_name.clear()
        
        logger.info("All processes stopped by admin command")

    async def restart_all_processes(self):
        """Restart all processes"""
        self.should_stop = False
        self.flood_wait_delay = 1  # Reset flood wait delay
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

    def is_m3u8_url(self, url: str) -> bool:
        """Check if URL is an M3U8 stream"""
        return url.lower().endswith('.m3u8') or 'm3u8' in url.lower()

    def parse_txt_file_content(self, content: str) -> List[Dict[str, str]]:
        """Parse TXT file content to extract video names and URLs"""
        videos = []
        lines = content.strip().split('\n')
        
        for i, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Try to parse "video_name : url" format
            if ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    name = parts[0].strip()
                    url = parts[1].strip()
                    
                    # Validate URL
                    if url.startswith(('http://', 'https://')):
                        # Sanitize filename and ensure it has .mp4 extension
                        if not name.lower().endswith('.mp4'):
                            name += '.mp4'
                        sanitized_name = self.sanitize_filename(name)
                        videos.append({'name': sanitized_name, 'url': url, 'line_number': i})
            else:
                # Treat the whole line as URL and generate filename
                if line.startswith(('http://', 'https://')):
                    filename = f"video_{len(videos) + 1}.mp4"
                    videos.append({'name': filename, 'url': line, 'line_number': i})
        
        return videos

    def apply_course_name_to_videos(self, videos: List[Dict[str, str]], course_name: str) -> List[Dict[str, str]]:
        """Apply course name to video filenames"""
        if not course_name or course_name.lower() == 'no':
            return videos
        
        # Sanitize course name
        sanitized_course_name = self.sanitize_filename(course_name)
        
        updated_videos = []
        for video in videos:
            original_name = video['name']
            
            # Split name and extension
            if '.' in original_name:
                name_part = '.'.join(original_name.split('.')[:-1])
                extension = original_name.split('.')[-1]
                new_name = f"{name_part}_{sanitized_course_name}.{extension}"
            else:
                new_name = f"{original_name}_{sanitized_course_name}"
            
            updated_video = video.copy()
            updated_video['name'] = new_name
            updated_videos.append(updated_video)
        
        return updated_videos

    async def download_m3u8_with_ffmpeg(self, url: str, output_path: str, progress_msg, filename: str):
        """Download M3U8 stream using ffmpeg with progress tracking"""
        try:
            # Use ffmpeg to download M3U8 stream
            cmd = [
                'ffmpeg',
                '-i', url,
                '-c', 'copy',
                '-bsf:a', 'aac_adtstoasc',
                '-y',  # Overwrite output file
                output_path
            ]
            
            # Start ffmpeg process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            start_time = time.time()
            last_update = start_time
            
            # Monitor progress
            while True:
                if self.should_stop:
                    process.terminate()
                    raise Exception("Download stopped by admin command")
                
                # Check if process is still running
                if process.poll() is not None:
                    break
                
                current_time = time.time()
                elapsed = current_time - start_time
                
                # Update progress message every 5 seconds
                if current_time - last_update >= 5:
                    await self.safe_edit_message(progress_msg,
                        f"📹 **Downloading M3U8 Stream...**\n\n"
                        f"📁 {filename}\n"
                        f"⏱️ Time: {elapsed:.0f}s\n"
                        f"🔄 Processing stream segments..."
                    )
                    last_update = current_time
                
                await asyncio.sleep(1)
            
            # Check if download was successful
            if process.returncode == 0:
                # Get file size
                file_size = os.path.getsize(output_path)
                return file_size
            else:
                stderr_output = process.stderr.read() if process.stderr else "Unknown error"
                raise Exception(f"FFmpeg failed: {stderr_output}")
                
        except Exception as e:
            logger.error(f"Error downloading M3U8: {e}")
            raise

    async def add_to_queue(self, user_id: int, upload_item: dict):
        """Add upload item to user's queue"""
        if self.should_stop:
            return
            
        if user_id not in self.upload_queues:
            self.upload_queues[user_id] = deque()
        
        self.upload_queues[user_id].append(upload_item)
        await self.process_queue(user_id)

    async def handle_flood_wait(self, func, *args, **kwargs):
        """Handle flood wait errors with exponential backoff"""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except FloodWaitError as e:
                if attempt == max_retries - 1:
                    raise
                
                wait_time = e.seconds + self.flood_wait_delay
                logger.warning(f"Flood wait detected, waiting {wait_time} seconds (attempt {attempt + 1})")
                await asyncio.sleep(wait_time)
                
                # Increase delay for next operation
                self.flood_wait_delay = min(self.flood_wait_delay * 2, 60)
            except Exception as e:
                raise

    async def safe_edit_message(self, message, text, **kwargs):
        """Safely edit message with flood wait handling"""
        return await self.handle_flood_wait(message.edit, text, **kwargs)

    async def safe_respond(self, event, text, **kwargs):
        """Safely respond to event with flood wait handling"""
        return await self.handle_flood_wait(event.respond, text, **kwargs)

    async def process_queue(self, user_id: int):
        """Process upload queue for a user with flood wait protection"""
        if self.should_stop or (user_id in self.processing_queues and self.processing_queues[user_id]):
            return  # Already processing or stopped
        
        if user_id not in self.upload_queues or not self.upload_queues[user_id]:
            return  # No items in queue
        
        self.processing_queues[user_id] = True
        
        try:
            while self.upload_queues[user_id] and not self.should_stop:
                upload_item = self.upload_queues[user_id].popleft()
                
                # Update active uploads
                remaining_count = len(self.upload_queues[user_id])
                self.active_uploads[user_id] = {
                    'filename': upload_item['filename'],
                    'status': f"Processing... ({remaining_count} remaining in queue)"
                }
                
                try:
                    if upload_item['type'] == 'file':
                        await self.process_file_upload(upload_item)
                    elif upload_item['type'] == 'url':
                        await self.process_url_upload(upload_item)
                    elif upload_item['type'] == 'm3u8':
                        await self.process_m3u8_upload(upload_item)
                    elif upload_item['type'] == 'txt_m3u8':
                        await self.process_txt_m3u8_upload(upload_item)
                    
                    # Add delay between queue items to prevent flood wait
                    if self.upload_queues[user_id]:  # If more items in queue
                        await asyncio.sleep(self.flood_wait_delay)
                        
                except Exception as e:
                    logger.error(f"Error processing queue item: {e}")
                    # Continue with next item instead of stopping entire queue
                
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
        
        progress_msg = await self.safe_respond(event, "📥 **Downloading from Telegram...**\n⏳ Starting...")
        
        # Use temporary file for streaming
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            try:
                # Download file with progress to temporary file
                await self.download_telegram_file_streaming(document, temp_file, progress_msg, filename)
                
                # Upload to GitHub from temporary file
                await self.safe_edit_message(progress_msg, "📤 **Uploading to GitHub...**\n⏳ Starting...")
                download_url = await self.upload_to_github_streaming(temp_file.name, filename, file_size, progress_msg)
                
                remaining = len(self.upload_queues.get(user_id, []))
                queue_text = f"\n\n📋 **Queue:** {remaining} files remaining" if remaining > 0 else ""
                
                await self.safe_edit_message(progress_msg,
                    f"✅ **Upload Complete!**\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}{queue_text}"
                )
                
            except Exception as e:
                logger.error(f"Error uploading file: {e}")
                await self.safe_edit_message(progress_msg, f"❌ **Upload Failed**\n\nError: {str(e)}")
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
        
        progress_msg = await self.safe_respond(event, "📥 **Downloading from URL...**\n⏳ Starting...")
        
        # Use temporary file for streaming
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            try:
                # Download from URL with progress to temporary file
                file_size = await self.download_from_url_streaming(url, temp_file, progress_msg, filename)
                
                # Upload to GitHub from temporary file
                await self.safe_edit_message(progress_msg, "📤 **Uploading to GitHub...**\n⏳ Starting...")
                download_url = await self.upload_to_github_streaming(temp_file.name, filename, file_size, progress_msg)
                
                remaining = len(self.upload_queues.get(user_id, []))
                queue_text = f"\n\n📋 **Queue:** {remaining} files remaining" if remaining > 0 else ""
                
                await self.safe_edit_message(progress_msg,
                    f"✅ **Upload Complete!**\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}{queue_text}"
                )
                
            except Exception as e:
                logger.error(f"Error processing URL: {e}")
                await self.safe_edit_message(progress_msg, f"❌ **Upload Failed**\n\nError: {str(e)}")
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
        
        progress_msg = await self.safe_respond(event, "📹 **Downloading M3U8 Stream...**\n⏳ Starting...")
        
        # Use temporary file for M3U8 download
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
            try:
                # Download M3U8 with ffmpeg
                file_size = await self.download_m3u8_with_ffmpeg(url, temp_file.name, progress_msg, filename)
                
                # Upload to GitHub from temporary file
                await self.safe_edit_message(progress_msg, "📤 **Uploading to GitHub...**\n⏳ Starting...")
                download_url = await self.upload_to_github_streaming(temp_file.name, filename, file_size, progress_msg)
                
                remaining = len(self.upload_queues.get(user_id, []))
                queue_text = f"\n\n📋 **Queue:** {remaining} files remaining" if remaining > 0 else ""
                
                await self.safe_edit_message(progress_msg,
                    f"✅ **M3U8 Upload Complete!**\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}{queue_text}"
                )
                
            except Exception as e:
                logger.error(f"Error processing M3U8: {e}")
                await self.safe_edit_message(progress_msg, f"❌ **M3U8 Upload Failed**\n\nError: {str(e)}")
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file.name)
                except:
                    pass

    async def process_txt_m3u8_upload(self, upload_item: dict):
        """Process TXT file containing M3U8 URLs with course name and start position option"""
        event = upload_item['event']
        document = upload_item['document']
        user_id = upload_item['user_id']
        
        progress_msg = await self.safe_respond(event, "📄 **Processing TXT file...**\n⏳ Reading content...")
        
        # Download TXT file content
        txt_content = await self.client.download_media(document, file=bytes)
        txt_content = txt_content.decode('utf-8')
        
        # Parse TXT file to extract video URLs
        videos = self.parse_txt_file_content(txt_content)
        
        if not videos:
            await self.safe_edit_message(progress_msg, "❌ **No valid URLs found in TXT file**\n\nExpected format: video_name : https://example.com/video.m3u8")
            return
        
        # Store parsed videos for course name selection
        self.pending_course_name[user_id] = {
            'videos': videos,
            'event': event,
            'progress_msg': progress_msg
        }
        
        # Create video list for user to see
        video_list = ""
        for i, video in enumerate(videos[:10], 1):  # Show first 10 videos
            video_list += f"**{i}.** `{video['name']}`\n"
        
        if len(videos) > 10:
            video_list += f"... and {len(videos) - 10} more videos"
        
        # Create buttons for course name selection
        buttons = [
            [Button.inline("📚 Add Course Name", "course_yes")],
            [Button.inline("❌ No Course Name", "course_no")]
        ]
        
        await self.safe_edit_message(progress_msg,
            f"📋 **Found {len(videos)} videos in TXT file**\n\n"
            f"📝 **Video List:**\n{video_list}\n\n"
            f"📚 **Add course name to video filenames?**\n"
            f"This will append course name to each video name.\n"
            f"Example: `class_1.mp4` → `class_1_math_course.mp4`",
            buttons=buttons
        )

    async def process_course_name_selection(self, user_id: int, add_course_name: bool):
        """Process course name selection for TXT upload"""
        if user_id not in self.pending_course_name:
            return
        
        pending_data = self.pending_course_name[user_id]
        videos = pending_data['videos']
        event = pending_data['event']
        progress_msg = pending_data['progress_msg']
        
        if add_course_name:
            await self.safe_edit_message(progress_msg,
                f"📚 **Enter Course Name**\n\n"
                f"📝 **Send the course name** to append to video filenames\n"
                f"Example: Send `Math Course` to rename videos like:\n"
                f"• `class_1.mp4` → `class_1_Math_Course.mp4`\n"
                f"• `lesson_2.mp4` → `lesson_2_Math_Course.mp4`\n\n"
                f"⏰ This selection will expire in 3 minutes if not used."
            )
        else:
            # Skip course name, proceed to start position selection
            await self.show_start_position_selection(user_id, videos, event, progress_msg)
            # Clean up pending course name data
            del self.pending_course_name[user_id]

    async def process_course_name_input(self, user_id: int, course_name: str):
        """Process course name input and proceed to start position selection"""
        if user_id not in self.pending_course_name:
            return
        
        pending_data = self.pending_course_name[user_id]
        videos = pending_data['videos']
        event = pending_data['event']
        progress_msg = pending_data['progress_msg']
        
        # Apply course name to videos
        updated_videos = self.apply_course_name_to_videos(videos, course_name)
        
        await self.show_start_position_selection(user_id, updated_videos, event, progress_msg)
        
        # Clean up pending course name data
        del self.pending_course_name[user_id]

    async def show_start_position_selection(self, user_id: int, videos: List[Dict[str, str]], event, progress_msg):
        """Show start position selection for TXT upload"""
        # Store updated videos for start position selection
        self.pending_txt_uploads[user_id] = {
            'videos': videos,
            'event': event,
            'progress_msg': progress_msg
        }
        
        # Create video list for user to see
        video_list = ""
        for i, video in enumerate(videos[:10], 1):  # Show first 10 videos
            video_list += f"**{i}.** `{video['name']}`\n"
        
        if len(videos) > 10:
            video_list += f"... and {len(videos) - 10} more videos"
        
        # Create buttons for start position
        buttons = []
        
        # Create number buttons (1-10 or total videos if less than 10)
        button_row = []
        max_buttons = min(len(videos), 10)
        
        for i in range(1, max_buttons + 1):
            button_row.append(Button.inline(str(i), f"start_{i}"))
            if len(button_row) == 5:  # 5 buttons per row
                buttons.append(button_row)
                button_row = []
        
        if button_row:  # Add remaining buttons
            buttons.append(button_row)
        
        # Add "All" and "Custom" buttons
        action_buttons = [
            Button.inline("📥 All", "start_all"),
            Button.inline("✏️ Custom", "start_custom")
        ]
        buttons.append(action_buttons)
        
        # Add cancel button
        buttons.append([Button.inline("❌ Cancel", "start_cancel")])
        
        await self.safe_edit_message(progress_msg,
            f"📋 **Ready to upload {len(videos)} videos**\n\n"
            f"📝 **Final Video List:**\n{video_list}\n\n"
            f"🎯 **Where to start uploading?**\n"
            f"Choose a number to start from that position:",
            buttons=buttons
        )

    async def process_txt_start_selection(self, user_id: int, start_position: int):
        """Process TXT upload starting from specified position"""
        if user_id not in self.pending_txt_uploads:
            return
        
        pending_data = self.pending_txt_uploads[user_id]
        videos = pending_data['videos']
        event = pending_data['event']
        progress_msg = pending_data['progress_msg']
        
        # Validate start position
        if start_position < 1 or start_position > len(videos):
            await self.safe_edit_message(progress_msg, 
                f"❌ **Invalid start position**\n\n"
                f"Please choose a number between 1 and {len(videos)}")
            return
        
        # Get videos starting from specified position
        selected_videos = videos[start_position - 1:]  # Convert to 0-based index
        
        await self.safe_edit_message(progress_msg, 
            f"✅ **Starting upload from video #{start_position}**\n\n"
            f"📊 **Processing {len(selected_videos)} videos**\n"
            f"🔄 Adding to queue...")
        
        # Add each video to queue starting from specified position
        for i, video in enumerate(selected_videos):
            upload_item = {
                'type': 'm3u8',
                'event': event,
                'url': video['url'],
                'filename': video['name'],
                'user_id': user_id
            }
            
            if user_id not in self.upload_queues:
                self.upload_queues[user_id] = deque()
            
            self.upload_queues[user_id].append(upload_item)
        
        await self.safe_edit_message(progress_msg, 
            f"✅ **{len(selected_videos)} videos added to queue**\n\n"
            f"🎯 **Started from video #{start_position}:** `{selected_videos[0]['name']}`\n"
            f"🔄 **Processing will start automatically...**")
        
        # Clean up pending data
        del self.pending_txt_uploads[user_id]
        
        # Start processing the queue
        await self.process_queue(user_id)

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
                "• M3U8 stream downloads with FFmpeg\n"
                "• TXT files with video lists (video_name : url format)\n"
                "• Add course names to video filenames\n"
                "• Choose starting position for TXT uploads\n"
                "• Real-time progress with speed display\n"
                "• Queue system for batch uploads\n"
                "• Flood wait protection\n\n"
                "**Commands:**\n"
                "• Send any file (up to 4GB)\n"
                "• Send a URL to download and upload\n"
                "• Send M3U8 stream URL for video download\n"
                "• Send TXT file with video list\n"
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

        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            user_id = event.sender_id
            is_admin = self.is_admin(user_id)
            
            basic_help = (
                "**How to use:**\n\n"
                "1. **File Upload**: Send any file directly to the bot\n"
                "2. **URL Upload**: Send a URL pointing to a file\n"
                "3. **M3U8 Stream**: Send M3U8 URL for video download\n"
                "4. **TXT Video List**: Send TXT file with format:\n"
                "   `video_name : https://example.com/video.m3u8`\n"
                "5. **Batch Upload**: Send multiple files/URLs - they'll queue automatically\n"
                "6. **Course Names**: Add course names to video filenames from TXT files\n"
                "7. **Start Position**: For TXT files, choose where to start uploading\n\n"
                "**Features:**\n"
                "• Supports files up to 4GB\n"
                "• M3U8 stream downloading with FFmpeg\n"
                "• Real-time progress updates with speed\n"
                "• Queue system for multiple uploads\n"
                "• Course name appending for organized uploads\n"
                "• Resume TXT uploads from any position\n"
                "• Flood wait protection for stability\n"
                "• Direct upload to GitHub releases\n"
                "• Returns download URL after upload\n\n"
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
            
            # Handle course name selection
            if data.startswith('course_'):
                if user_id not in self.pending_course_name:
                    await event.answer("This selection has expired", alert=True)
                    return
                
                if data == 'course_yes':
                    await self.process_course_name_selection(user_id, True)
                    await event.answer()
                elif data == 'course_no':
                    await self.process_course_name_selection(user_id, False)
                    await event.answer()
                return
            
            # Handle TXT upload start position selection
            if data.startswith('start_'):
                if user_id not in self.pending_txt_uploads:
                    await event.answer("This selection has expired", alert=True)
                    return
                
                if data == 'start_all':
                    await self.process_txt_start_selection(user_id, 1)
                    await event.answer()
                elif data == 'start_cancel':
                    if user_id in self.pending_txt_uploads:
                        progress_msg = self.pending_txt_uploads[user_id]['progress_msg']
                        await self.safe_edit_message(progress_msg, "❌ **TXT upload cancelled**")
                        del self.pending_txt_uploads[user_id]
                    await event.answer()
                elif data == 'start_custom':
                    pending_data = self.pending_txt_uploads[user_id]
                    progress_msg = pending_data['progress_msg']
                    total_videos = len(pending_data['videos'])
                    
                    await self.safe_edit_message(progress_msg,
                        f"✏️ **Custom Start Position**\n\n"
                        f"📊 **Total videos:** {total_videos}\n\n"
                        f"📝 **Send a number (1-{total_videos}) to start from that position**\n"
                        f"Example: Send `5` to start from video #5\n\n"
                        f"⏰ This selection will expire in 2 minutes if not used.")
                    await event.answer()
                else:
                    # Extract number from start_X
                    try:
                        start_num = int(data.split('_')[1])
                        await self.process_txt_start_selection(user_id, start_num)
                        await event.answer()
                    except (ValueError, IndexError):
                        await event.answer("Invalid selection", alert=True)
                return
            
            # Admin-only callback handling
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

        @self.client.on(events.NewMessage(pattern=r'/delete (.+)'))
        async def delete_handler(event):
            user_id = event.sender_id
            if not self.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            try:
                delete_args = event.pattern_match.group(1).strip()
                file_numbers = self.parse_delete_numbers(delete_args)
                
                if not file_numbers:
                    await event.respond("❌ **Invalid format**\n\nExamples:\n• /delete 5\n• /delete 1,3,5\n• /delete 1-5\n• /delete 1-3,7,9-12")
                    return
                
                assets = await self.github_uploader.list_release_assets()
                if not assets:
                    await event.respond("📂 **No files found in release**")
                    return
                
                # Validate all file numbers
                invalid_numbers = [num for num in file_numbers if num < 1 or num > len(assets)]
                if invalid_numbers:
                    await event.respond(f"❌ **Invalid file numbers:** {', '.join(map(str, invalid_numbers))}\n\nValid range: 1-{len(assets)}")
                    return
                
                # Remove duplicates and sort in descending order (delete from end to avoid index shifting)
                file_numbers = sorted(set(file_numbers), reverse=True)
                
                # Get files to delete
                files_to_delete = []
                for num in file_numbers:
                    asset = assets[num - 1]  # Convert to 0-based index
                    files_to_delete.append((num, asset['name']))
                
                # Confirm deletion
                if len(files_to_delete) == 1:
                    confirm_msg = f"🗑️ **Delete 1 file?**\n\n**{files_to_delete[0][0]}.** `{files_to_delete[0][1]}`"
                else:
                    file_list = "\n".join([f"**{num}.** `{name}`" for num, name in files_to_delete[:10]])
                    if len(files_to_delete) > 10:
                        file_list += f"\n... and {len(files_to_delete) - 10} more files"
                    confirm_msg = f"🗑️ **Delete {len(files_to_delete)} files?**\n\n{file_list}"
                
                progress_msg = await event.respond(f"{confirm_msg}\n\n⏳ **Starting deletion...**")
                
                # Delete files
                deleted_count = 0
                failed_files = []
                
                for i, (num, filename) in enumerate(files_to_delete, 1):
                    try:
                        success = await self.github_uploader.delete_asset_by_name(filename)
                        if success:
                            deleted_count += 1
                        else:
                            failed_files.append(f"{num}. {filename}")
                        
                        # Update progress
                        await progress_msg.edit(
                            f"{confirm_msg}\n\n"
                            f"⏳ **Progress:** {i}/{len(files_to_delete)} files processed\n"
                            f"✅ **Deleted:** {deleted_count} files"
                        )
                        
                    except Exception as e:
                        failed_files.append(f"{num}. {filename} (Error: {str(e)})")
                
                # Final result
                result_msg = f"✅ **Deletion Complete**\n\n📊 **Successfully deleted:** {deleted_count}/{len(files_to_delete)} files"
                
                if failed_files:
                    failed_list = "\n".join(failed_files[:5])
                    if len(failed_files) > 5:
                        failed_list += f"\n... and {len(failed_files) - 5} more"
                    result_msg += f"\n\n❌ **Failed to delete:**\n{failed_list}"
                
                await progress_msg.edit(result_msg)
                
            except ValueError:
                await event.respond("❌ **Invalid format**\n\nExamples:\n• /delete 5\n• /delete 1,3,5\n• /delete 1-5\n• /delete 1-3,7,9-12")
            except Exception as e:
                await event.respond(f"❌ **Error deleting files**\n\n{str(e)}")
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
                
                # Sanitize the new filename
                sanitized_filename = self.sanitize_filename(new_filename)
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
                
                success = await self.github_uploader.rename_asset_fast(old_filename, sanitized_filename)
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

            # Handle course name input for TXT uploads
            if (user_id in self.pending_course_name and 
                event.message.text and 
                not event.message.document):
                
                course_name = event.message.text.strip()
                await self.process_course_name_input(user_id, course_name)
                return

            # Handle custom start position for TXT uploads
            if (user_id in self.pending_txt_uploads and 
                event.message.text and 
                event.message.text.strip().isdigit()):
                
                start_position = int(event.message.text.strip())
                await self.process_txt_start_selection(user_id, start_position)
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
                        if self.is_m3u8_url(text):
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
                            "• An M3U8 stream URL\n"
                            "• A TXT file with video list\n\n"
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
        
        # Check if it's a TXT file with M3U8 URLs
        if filename.lower().endswith('.txt'):
            # Add to queue as TXT M3U8 processing
            upload_item = {
                'type': 'txt_m3u8',
                'event': event,
                'document': document,
                'filename': filename,
                'user_id': user_id
            }
            
            await event.respond(f"📄 **TXT File Received**\n\n📁 **File:** `{filename}`\n🔄 **Processing video list...**")
            await self.add_to_queue(user_id, upload_item)
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

    async def handle_m3u8_upload(self, event):
        """Handle M3U8 URL upload by adding to queue"""
        user_id = event.sender_id
        url = event.message.text.strip()
        
        # Extract filename from URL or generate one
        filename = url.split('/')[-1] or f"stream_{int(time.time())}"
        if '?' in filename:
            filename = filename.split('?')[0]
        
        # Ensure .mp4 extension for M3U8 downloads
        if not filename.lower().endswith('.mp4'):
            filename = filename.replace('.m3u8', '.mp4') if filename.endswith('.m3u8') else f"{filename}.mp4"
        
        # Sanitize filename
        sanitized_filename = self.sanitize_filename(filename)
        if sanitized_filename != filename:
            logger.info(f"Sanitized filename: '{filename}' -> '{sanitized_filename}'")
        
        logger.info(f"Queuing M3U8: {url}")
        
        # Add to queue
        upload_item = {
            'type': 'm3u8',
            'event': event,
            'url': url,
            'filename': sanitized_filename,
            'user_id': user_id
        }
        
        queue_position = len(self.upload_queues.get(user_id, [])) + 1
        await event.respond(f"📹 **M3U8 Stream Queued**\n\n🔗 **URL:** `{url}`\n📁 **File:** `{sanitized_filename}`\n🔢 **Position:** {queue_position}")
        
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
                await self.safe_edit_message(progress_msg,
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
                            await self.safe_edit_message(progress_msg,
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
                await self.safe_edit_message(progress_msg,
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

async def main():
    bot = TelegramBot()
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())
