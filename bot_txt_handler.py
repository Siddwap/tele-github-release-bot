
import logging
from telegram import Update
from telegram.ext import ContextTypes
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
    
    async def handle_txt_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Handle txt file upload"""
        try:
            # Check if user is admin
            if not self.config.is_admin(update.effective_user.id):
                await update.message.reply_text("❌ You don't have permission to use this command.")
                return True
            
            # Check for txt file
            if not update.message.document:
                return False
            
            document = update.message.document
            if not document.file_name.lower().endswith('.txt'):
                return False
            
            # Check for command in caption or previous message
            command_text = update.message.caption or ""
            is_txt_cmd, return_links = self.is_txt_command(command_text)
            
            if not is_txt_cmd:
                # Check if this is a regular txt file upload (treat as M3U8 list by default)
                # This maintains backward compatibility
                return False
            
            # Download txt file
            file = await context.bot.get_file(document.file_id)
            file_content = await file.download_as_bytearray()
            txt_content = file_content.decode('utf-8')
            
            # Send initial message
            status_msg = await update.message.reply_text("📝 Processing txt file upload...")
            
            # Create progress callback
            async def progress_callback(message, percent):
                try:
                    await status_msg.edit_text(f"📝 {message}\nProgress: {percent}%")
                except:
                    pass  # Ignore edit errors
            
            # Process the upload
            result = await self.txt_handler.process_txt_upload(
                txt_content, 
                return_links=return_links,
                progress_callback=progress_callback
            )
            
            # Send final result
            await status_msg.edit_text(result)
            return True
            
        except Exception as e:
            logger.error(f"Error handling txt file: {e}")
            await update.message.reply_text(f"❌ Error processing txt file: {str(e)}")
            return True
    
    async def handle_txt_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Handle txt help command"""
        try:
            if not update.message.text:
                return False
            
            if not update.message.text.strip().lower().startswith('/txt_help'):
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

2. Upload the txt file with one of these captions:
   - `/txt_upload` - Just upload files
   - `/txt_links` - Upload files and get GitHub links back

**Features:**
• ✅ Supports MP4, PDF, M3U8, and other file types
• ✅ Automatically detects M3U8 files and processes them correctly
• ✅ Preserves original filenames
• ✅ Returns GitHub download links when requested
• ✅ Shows upload progress

**Example:**
Upload a txt file with caption `/txt_links` to get:
```
filename1.mp4 : https://github.com/repo/releases/download/tag/filename1.mp4
filename2.pdf : https://github.com/repo/releases/download/tag/filename2.pdf
```
            """
            
            await update.message.reply_text(help_text, parse_mode='Markdown')
            return True
            
        except Exception as e:
            logger.error(f"Error in txt help: {e}")
            return False
