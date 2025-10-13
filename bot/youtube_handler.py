"""
YouTube video handling - fetching, downloading, and uploading
"""
import logging
import os
from typing import Dict, Optional
from telethon.tl.custom import Button
from bot.download_handlers import fetch_youtube_video_data, download_youtube_with_pytubefix
from bot.upload_handlers import upload_to_github_streaming

logger = logging.getLogger(__name__)


class YouTubeHandler:
    """Handles YouTube video downloads and uploads"""
    
    def __init__(self, bot):
        self.bot = bot
        self.youtube_pending: Dict[int, Dict] = {}
    
    async def handle_youtube_url(self, event, youtube_url: str):
        """Handle YouTube URL - fetch video data and show quality options"""
        user_id = event.sender_id
        
        progress_msg = await event.respond(
            "🎬 **Fetching YouTube video data...**\n"
            "⏳ Please wait..."
        )
        
        try:
            video_data = await fetch_youtube_video_data(youtube_url)
            
            if not video_data or 'medias' not in video_data or not video_data['medias']:
                await progress_msg.edit("❌ **Failed to fetch video data**\n\nPlease check the URL and try again.")
                return
            
            if not video_data['medias'][0].get('formats'):
                await progress_msg.edit("❌ **No suitable video formats found**\n\nPlease try a different video or use a direct download link.")
                return
            
            title = video_data.get('text', 'YouTube Video')
            formats = video_data['medias'][0]['formats']
            
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
            
            buttons.append([Button.inline("❌ Cancel", f"yt_cancel_{user_id}")])
            
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
    
    async def process_youtube_upload(self, event, youtube_url: str, quality: int, video_data: Dict):
        """Process YouTube video download and upload"""
        user_id = event.sender_id
        
        try:
            title = video_data.get('text', 'YouTube Video')
            safe_title = self.bot.sanitize_filename_preserve_unicode(title)
            filename = f"{safe_title}_{quality}p.mp4"
            
            progress_msg = await event.respond(
                f"🎬 **Processing YouTube Video**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Quality:** {quality}p\n"
                f"⏳ **Status:** Starting download..."
            )
            
            merged_file_path = await download_youtube_with_pytubefix(
                youtube_url,
                quality,
                filename,
                progress_msg,
                self.bot.format_size
            )
            
            file_size = os.path.getsize(merged_file_path)
            
            await progress_msg.edit(
                f"📤 **Uploading to GitHub...**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Size:** {self.bot.format_size(file_size)}\n"
                f"⏳ **Status:** Uploading..."
            )
            
            await upload_to_github_streaming(
                self.bot.github_uploader, merged_file_path, filename, file_size, progress_msg,
                self.bot.format_size, self.bot.queue_manager.upload_queues, self.bot.should_stop,
                1, 1
            )
            
            download_url = f"https://github.com/{self.bot.config.github_repo}/releases/download/{self.bot.config.github_release_tag}/{filename}"
            
            await progress_msg.edit(
                f"✅ **YouTube Upload Complete!**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Size:** {self.bot.format_size(file_size)}\n"
                f"📊 **Quality:** {quality}p\n"
                f"🔗 **Download URL:**\n{download_url}"
            )
            
            try:
                os.unlink(merged_file_path)
            except:
                pass
                
        except Exception as e:
            logger.error(f"Error processing YouTube upload: {e}")
            await event.respond(f"❌ **YouTube Upload Failed**\n\nError: {str(e)}")
