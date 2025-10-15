"""
YouTube video handling - fetching, downloading, and uploading
"""
import logging
import os
import re
from typing import Dict, Optional
from telethon.tl.custom import Button
from bot.download_handlers import download_youtube_with_ytdlp
from bot.upload_handlers import upload_to_github_streaming

logger = logging.getLogger(__name__)


class YouTubeHandler:
    """Handles YouTube video downloads and uploads"""
    
    def __init__(self, bot):
        self.bot = bot
        self.youtube_pending: Dict[int, Dict] = {}
        self.quality_options = [320, 480, 720]  # Predefined quality options
    
    async def handle_youtube_url(self, event, youtube_url: str):
        """Handle YouTube URL - show quality options without fetching video data"""
        user_id = event.sender_id
        
        try:
            # Extract video ID and check if it's a live stream
            video_id = self._extract_video_id(youtube_url)
            is_live = self._is_live_stream(youtube_url)
            
            # Store pending YouTube download
            self.youtube_pending[user_id] = {
                'url': youtube_url,
                'event': event,
                'video_id': video_id,
                'is_live': is_live
            }
            
            # Create quality selection buttons
            buttons = []
            for quality in self.quality_options:
                button_text = f"{quality}p"
                callback_data = f"yt_quality_{quality}_{user_id}"
                buttons.append([Button.inline(button_text, callback_data)])
            
            # Add live stream specific option if it's a live stream
            if is_live:
                buttons.append([Button.inline("🎥 Live Stream (Best Quality)", f"yt_quality_live_{user_id}")])
            
            buttons.append([Button.inline("❌ Cancel", f"yt_cancel_{user_id}")])
            
            message_text = self._build_initial_message(youtube_url, is_live)
            
            await event.respond(message_text, buttons=buttons)
            
        except Exception as e:
            logger.error(f"Error handling YouTube URL: {e}")
            await event.respond(f"❌ **Error processing YouTube URL**\n\n{str(e)}")
    
    async def process_youtube_upload(self, event, youtube_url: str, quality: str):
        """Process YouTube video download and upload"""
        user_id = event.sender_id
        
        try:
            # Get pending data
            pending_data = self.youtube_pending.get(user_id, {})
            video_id = pending_data.get('video_id', self._extract_video_id(youtube_url))
            is_live = pending_data.get('is_live', False)
            
            # Generate filename based on URL and quality
            if is_live and quality == 'live':
                filename = f"youtube_live_{video_id}_best_quality.mp4"
                quality_display = "Live Stream (Best Available)"
                actual_quality = "best"  # yt-dlp will choose best quality for live streams
            else:
                filename = f"youtube_video_{video_id}_{quality}p.mp4"
                quality_display = f"{quality}p"
                actual_quality = quality
            
            progress_msg = await event.respond(
                f"🎬 **Processing YouTube {'Live Stream' if is_live else 'Video'}**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Quality:** {quality_display}\n"
                f"🔗 **URL:** {youtube_url}\n"
                f"⏳ **Status:** Starting download..."
            )
            
            # Download YouTube video/live stream
            merged_file_path = await download_youtube_with_ytdlp(
                youtube_url,
                actual_quality,
                filename,
                progress_msg,
                self.bot.format_size,
                is_live=is_live
            )
            
            if not merged_file_path or not os.path.exists(merged_file_path):
                await progress_msg.edit("❌ **Download failed**\n\nCould not download the video.")
                return
            
            file_size = os.path.getsize(merged_file_path)
            
            await progress_msg.edit(
                f"📤 **Uploading to GitHub...**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Size:** {self.bot.format_size(file_size)}\n"
                f"⏳ **Status:** Uploading..."
            )
            
            # Upload to GitHub
            await upload_to_github_streaming(
                self.bot.github_uploader, merged_file_path, filename, file_size, progress_msg,
                self.bot.format_size, self.bot.queue_manager.upload_queues, self.bot.should_stop,
                1, 1
            )
            
            download_url = f"https://github.com/{self.bot.config.github_repo}/releases/download/{self.bot.config.github_release_tag}/{filename}"
            
            await progress_msg.edit(
                f"✅ **YouTube {'Live Stream' if is_live else 'Video'} Upload Complete!**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Size:** {self.bot.format_size(file_size)}\n"
                f"📊 **Quality:** {quality_display}\n"
                f"🔗 **Download URL:**\n{download_url}"
            )
            
            # Clean up temporary file
            try:
                os.unlink(merged_file_path)
            except Exception as e:
                logger.warning(f"Could not delete temporary file: {e}")
                
        except Exception as e:
            logger.error(f"Error processing YouTube upload: {e}")
            await event.respond(f"❌ **YouTube Upload Failed**\n\nError: {str(e)}")
    
    def _extract_video_id(self, youtube_url: str) -> str:
        """Extract video ID from YouTube URL"""
        # Patterns for different YouTube URL formats
        patterns = [
            # Regular videos
            r'(?:youtube\.com/watch\?v=|youtu\.be/)([^&?\n]+)',
            r'youtube\.com/embed/([^&?\n]+)',
            r'youtube\.com/v/([^&?\n]+)',
            # Live streams
            r'youtube\.com/live/([^&?\n]+)',
            r'youtube\.com/watch\?v=([^&?\n]+).*&live=1',
            # Shorts
            r'youtube\.com/shorts/([^&?\n]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, youtube_url)
            if match:
                return match.group(1)
        
        # If no pattern matches, return a hash of the URL
        return str(hash(youtube_url))[-8:]
    
    def _is_live_stream(self, youtube_url: str) -> bool:
        """Check if the URL is a YouTube live stream"""
        live_patterns = [
            r'youtube\.com/live/',
            r'youtube\.com/watch.*&live=1',
            r'youtube\.com/watch.*feature=live',
        ]
        
        for pattern in live_patterns:
            if re.search(pattern, youtube_url):
                return True
        
        return False
    
    def _build_initial_message(self, youtube_url: str, is_live: bool) -> str:
        """Build the initial message based on URL type"""
        if is_live:
            return (
                f"🎥 **YouTube Live Stream URL Received**\n\n"
                f"🔗 **URL:** {youtube_url}\n"
                f"📡 **Type:** Live Stream\n\n"
                f"**Select Quality:**\n"
                f"• Standard qualities (320p, 480p, 720p)\n"
                f"• 🎥 Live Stream option for best available quality\n\n"
                f"*Note: Live streams may take longer to process*"
            )
        else:
            return (
                f"🎬 **YouTube URL Received**\n\n"
                f"🔗 **URL:** {youtube_url}\n"
                f"📹 **Type:** Regular Video\n\n"
                f"**Select Quality:**"
            )
    
    async def handle_quality_selection(self, event, quality: str, user_id: int):
        """Handle quality selection from user"""
        try:
            pending_data = self.youtube_pending.get(user_id)
            if not pending_data:
                await event.respond("❌ **Session expired**\n\nPlease start over with a new YouTube URL.")
                return
            
            youtube_url = pending_data['url']
            
            # Remove pending data
            if user_id in self.youtube_pending:
                del self.youtube_pending[user_id]
            
            await event.respond(f"✅ **Quality selected: {quality}p**\n\nStarting download process...")
            
            # Process the upload with selected quality
            await self.process_youtube_upload(event, youtube_url, quality)
            
        except Exception as e:
            logger.error(f"Error handling quality selection: {e}")
            await event.respond(f"❌ **Error processing quality selection**\n\n{str(e)}")
    
    async def handle_live_stream_selection(self, event, user_id: int):
        """Handle live stream quality selection"""
        try:
            pending_data = self.youtube_pending.get(user_id)
            if not pending_data:
                await event.respond("❌ **Session expired**\n\nPlease start over with a new YouTube URL.")
                return
            
            youtube_url = pending_data['url']
            
            # Remove pending data
            if user_id in self.youtube_pending:
                del self.youtube_pending[user_id]
            
            await event.respond("🎥 **Live Stream selected**\n\nStarting live stream download with best available quality...")
            
            # Process the upload with live quality
            await self.process_youtube_upload(event, youtube_url, 'live')
            
        except Exception as e:
            logger.error(f"Error handling live stream selection: {e}")
            await event.respond(f"❌ **Error processing live stream**\n\n{str(e)}")
