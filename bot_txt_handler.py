
import logging
from telethon.tl.types import DocumentAttributeFilename
from txt_file_handler import TxtFileHandler
from config import BotConfig
import asyncio

logger = logging.getLogger(__name__)

class BotTxtHandler:
    def __init__(self, config: BotConfig):
        self.config = config
        self.txt_handler = TxtFileHandler(config)
    
    def is_txt_command(self, text: str) -> tuple[bool, bool]:
        """Check if message is a txt command and if links should be returned"""
        if not text:
            return False, False
        
        text = text.strip().lower()
        
        # Check for txt upload command
        if text.startswith('/txt_upload'):
            return True, False
        
        # Check for txt upload with links command
        if text.startswith('/txt_links'):
            return True, True
        
        return False, False
    
    async def handle_txt_file(self, event) -> bool:
        """Handle txt file upload"""
        try:
            # Check if user is admin
            if not self.config.is_admin(event.sender_id):
                await event.respond("❌ You don't have permission to use this command.")
                return True
            
            # Check for txt file
            if not event.message.document:
                return False
            
            # Get filename
            file_name = "unknown.txt"
            for attr in event.message.document.attributes:
                if isinstance(attr, DocumentAttributeFilename):
                    file_name = attr.file_name
                    break
            
            if not file_name.lower().endswith('.txt'):
                return False
            
            # Check for command in caption or message text
            command_text = event.message.text or ""
            is_txt_cmd, return_links = self.is_txt_command(command_text)
            
            if not is_txt_cmd:
                # Check if this is a regular txt file upload (treat as M3U8 list by default)
                # This maintains backward compatibility
                return False
            
            # Download txt file
            file_path = await event.message.download_media()
            
            with open(file_path, 'r', encoding='utf-8') as f:
                txt_content = f.read()
            
            # Send initial message
            status_msg = await event.respond("📝 Processing txt file upload...")
            
            # Create progress callback
            async def progress_callback(message, percent):
                try:
                    await status_msg.edit(f"📝 {message}\nProgress: {percent}%")
                except:
                    pass  # Ignore edit errors
            
            # Process the upload
            result = await self.txt_handler.process_txt_upload(
                txt_content, 
                return_links=return_links,
                progress_callback=progress_callback
            )
            
            # Send final result
            await status_msg.edit(result)
            
            # Clean up temp file
            import os
            os.remove(file_path)
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling txt file: {e}")
            await event.respond(f"❌ Error processing txt file: {str(e)}")
            return True
    
    async def handle_txt_help(self, event) -> bool:
        """Handle txt help command"""
        try:
            if not event.message.text:
                return False
            
            if not event.message.text.strip().lower().startswith('/txt_help'):
                return False
            
            help_text = """
📋 **TXT File Upload Commands**

**Commands:**
• `/txt_upload` - Upload files from txt (filename:url format)
• `/txt_links` - Upload files and get GitHub links in txt format
• `/txt_help` - Show this help message

**Usage:**
1. Create a txt file with this format:
```
filename1.mp4 : https://example.com/video1.mp4
filename2.pdf : https://example.com/doc.pdf
filename3.m3u8 : https://example.com/playlist.m3u8
```

2. Upload the txt file with one of these commands as message text:
   - `/txt_upload` - Just upload files
   - `/txt_links` - Upload files and get GitHub links back

**Features:**
• ✅ Supports MP4, PDF, M3U8, and other file types
• ✅ Automatically detects M3U8 files and processes them correctly
• ✅ Preserves original filenames
• ✅ Returns GitHub download links when requested
• ✅ Shows upload progress

**Example:**
Upload a txt file with message `/txt_links` to get:
```
filename1.mp4 : https://github.com/repo/releases/download/tag/filename1.mp4
filename2.pdf : https://github.com/repo/releases/download/tag/filename2.pdf
```
            """
            
            await event.respond(help_text)
            return True
            
        except Exception as e:
            logger.error(f"Error in txt help: {e}")
            return False
