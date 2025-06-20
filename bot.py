
import asyncio
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from telethon import TelegramClient, events
from telethon.tl.types import DocumentAttributeFilename
import unicodedata

# Import existing modules
from config import BotConfig
from github_uploader import GitHubUploader
from response_formatter import format_upload_complete_message

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TelegramBot:
    def __init__(self):
        self.config = BotConfig.from_env()
        self.config.validate()
        
        self.client = TelegramClient(
            'bot_session',
            self.config.telegram_api_id,
            self.config.telegram_api_hash
        )
        
        self.uploader = GitHubUploader(self.config)
        
        # Setup event handlers
        self.setup_handlers()
    
    def normalize_filename(self, filename: str) -> str:
        """Normalize filename to handle Unicode characters properly"""
        try:
            # First, try to normalize Unicode characters
            normalized = unicodedata.normalize('NFC', filename)
            
            # Replace problematic characters but preserve Unicode letters and numbers
            # Keep alphanumeric, dots, hyphens, underscores, and Unicode letters/numbers
            safe_chars = []
            for char in normalized:
                if (char.isalnum() or 
                    char in '.-_' or 
                    unicodedata.category(char).startswith('L') or  # Letters (including Hindi)
                    unicodedata.category(char).startswith('N')):   # Numbers
                    safe_chars.append(char)
                elif char in ' ':
                    safe_chars.append('_')
                # Skip other special characters
            
            result = ''.join(safe_chars)
            
            # Ensure we don't have empty filename
            if not result or result == '.':
                result = 'unnamed_file'
            
            # Ensure extension is preserved
            if '.' in filename and not result.endswith(filename.split('.')[-1]):
                original_ext = filename.split('.')[-1]
                if original_ext and len(original_ext) <= 10:  # Reasonable extension length
                    result = result + '.' + original_ext
            
            logger.info(f"Normalized filename: '{filename}' -> '{result}'")
            return result
            
        except Exception as e:
            logger.error(f"Error normalizing filename '{filename}': {e}")
            # Fallback to simple ASCII conversion
            ascii_name = unicodedata.normalize('NFKD', filename).encode('ascii', 'ignore').decode('ascii')
            return ascii_name if ascii_name else 'unnamed_file'
    
    def detect_file_type_from_url(self, url: str, filename: str = "") -> str:
        """Detect file type from URL and filename"""
        # Check filename extension first
        if filename:
            filename_lower = filename.lower()
            if any(ext in filename_lower for ext in ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv']):
                return 'video'
            elif any(ext in filename_lower for ext in ['.pdf', '.doc', '.docx', '.txt', '.rtf']):
                return 'document'
            elif any(ext in filename_lower for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp']):
                return 'image'
            elif any(ext in filename_lower for ext in ['.mp3', '.wav', '.flac', '.aac']):
                return 'audio'
            elif filename_lower.endswith('.m3u8'):
                return 'm3u8'
        
        # Check URL for file type hints
        url_lower = url.lower()
        if any(ext in url_lower for ext in ['.mp4', '.avi', '.mkv', '.mov']):
            return 'video'
        elif any(ext in url_lower for ext in ['.pdf', '.doc', '.txt']):
            return 'document'
        elif '.m3u8' in url_lower or 'playlist' in url_lower:
            return 'm3u8'
        
        # Default fallback
        return 'unknown'
    
    def parse_txt_file_content(self, content: str) -> list:
        """Parse txt file content to extract filename:url pairs"""
        files_to_upload = []
        lines = content.strip().split('\n')
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith('#'):  # Skip empty lines and comments
                continue
            
            try:
                if ':' in line:
                    # Split only on first colon to handle URLs with colons
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        filename = parts[0].strip()
                        url = parts[1].strip()
                        
                        if filename and url:
                            # Detect file type
                            file_type = self.detect_file_type_from_url(url, filename)
                            files_to_upload.append({
                                'filename': filename,
                                'url': url,
                                'file_type': file_type,
                                'line_number': line_num
                            })
                        else:
                            logger.warning(f"Line {line_num}: Empty filename or URL")
                    else:
                        logger.warning(f"Line {line_num}: Invalid format (no colon separator)")
                else:
                    logger.warning(f"Line {line_num}: No colon separator found")
            except Exception as e:
                logger.error(f"Error parsing line {line_num}: {e}")
        
        return files_to_upload
    
    async def process_txt_file_upload(self, files_to_upload: list, return_as_txt: bool = False) -> str:
        """Process multiple file uploads from txt file"""
        successful_uploads = []
        failed_uploads = []
        
        for file_info in files_to_upload:
            try:
                filename = file_info['filename']
                url = file_info['url']
                file_type = file_info['file_type']
                
                logger.info(f"Processing {filename} ({file_type}) from {url}")
                
                # Normalize filename to handle Hindi/Unicode characters
                normalized_filename = self.normalize_filename(filename)
                
                # Upload based on file type
                if file_type == 'm3u8':
                    github_url = await self.uploader.upload_m3u8_from_url(url, normalized_filename)
                else:
                    # For non-M3U8 files, download and upload directly
                    github_url = await self.uploader.upload_file_from_url(url, normalized_filename)
                
                if github_url:
                    successful_uploads.append({
                        'original_filename': filename,
                        'normalized_filename': normalized_filename,
                        'github_url': github_url,
                        'file_type': file_type
                    })
                    logger.info(f"Successfully uploaded: {filename}")
                else:
                    failed_uploads.append(f"{filename} (Upload failed)")
                    
            except Exception as e:
                logger.error(f"Error uploading {file_info['filename']}: {e}")
                failed_uploads.append(f"{file_info['filename']} (Error: {str(e)})")
        
        # Generate response
        if return_as_txt:
            # Generate txt file with GitHub URLs
            txt_content = ""
            for upload in successful_uploads:
                txt_content += f"{upload['original_filename']} : {upload['github_url']}\n"
            
            if txt_content:
                # Create temporary txt file
                with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                    f.write(txt_content)
                    temp_txt_path = f.name
                
                try:
                    # Upload the txt file with results
                    result_filename = f"upload_results_{len(successful_uploads)}_files.txt"
                    github_txt_url = await self.uploader.upload_file(temp_txt_path, result_filename)
                    
                    # Clean up temp file
                    os.unlink(temp_txt_path)
                    
                    response = f"✅ Batch Upload Complete!\n\n"
                    response += f"📊 Results: {len(successful_uploads)} successful, {len(failed_uploads)} failed\n\n"
                    response += f"📄 Download results as TXT file:\n{github_txt_url}\n\n"
                    
                    if failed_uploads:
                        response += f"❌ Failed uploads:\n"
                        for failed in failed_uploads[:5]:  # Show first 5 failures
                            response += f"• {failed}\n"
                        if len(failed_uploads) > 5:
                            response += f"... and {len(failed_uploads) - 5} more\n"
                    
                    return response
                    
                except Exception as e:
                    logger.error(f"Error creating result txt file: {e}")
                    # Fallback to regular response
        
        # Regular response format
        response = f"✅ Batch Upload Complete!\n\n"
        response += f"📊 Results: {len(successful_uploads)} successful, {len(failed_uploads)} failed\n\n"
        
        if successful_uploads:
            response += "✅ Successful uploads:\n"
            for upload in successful_uploads[:10]:  # Show first 10
                response += f"📁 {upload['original_filename']}\n"
                response += f"🔗 {upload['github_url']}\n\n"
            
            if len(successful_uploads) > 10:
                response += f"... and {len(successful_uploads) - 10} more files\n\n"
        
        if failed_uploads:
            response += "❌ Failed uploads:\n"
            for failed in failed_uploads[:5]:  # Show first 5 failures
                response += f"• {failed}\n"
            if len(failed_uploads) > 5:
                response += f"... and {len(failed_uploads) - 5} more\n"
        
        return response
    
    def setup_handlers(self):
        @self.client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            if not self.config.is_admin(event.sender_id):
                await event.respond("❌ Access denied. This bot is for authorized users only.")
                return
            
            welcome_msg = """
🚀 **GitHub File Upload Bot**

Commands:
📤 `/upload` - Upload files to GitHub
📋 `/txt_upload` - Upload multiple files from txt list
📄 `/txt_links` - Upload files and get result as txt file
🆔 `/info` - Show your user ID
ℹ️ `/help` - Show detailed help

Just send me a file or M3U8 URL to upload!
            """
            await event.respond(welcome_msg)
        
        @self.client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            if not self.config.is_admin(event.sender_id):
                await event.respond("❌ Access denied.")
                return
            
            help_msg = """
📖 **Detailed Help**

**File Upload Methods:**
1️⃣ Send any file directly
2️⃣ Send M3U8 URL for streaming content
3️⃣ Send txt file with multiple URLs

**TXT File Format:**
```
filename1.mp4 : https://example.com/video1.mp4
filename2.pdf : https://example.com/document.pdf
filename3.m3u8 : https://example.com/stream.m3u8
```

**Commands:**
• `/txt_upload` - Process txt file normally
• `/txt_links` - Get results as downloadable txt file
• `/info` - Your Telegram user ID

**Features:**
✅ Supports all file types (video, document, image, audio)
✅ Handles Hindi/Unicode filenames properly
✅ Batch upload from txt files
✅ M3U8 streaming content support
✅ Automatic file type detection
            """
            await event.respond(help_msg)
        
        @self.client.on(events.NewMessage(pattern='/info'))
        async def info_handler(event):
            user_id = event.sender_id
            await event.respond(f"👤 Your Telegram User ID: `{user_id}`")
        
        @self.client.on(events.NewMessage(pattern='/txt_upload'))
        async def txt_upload_handler(event):
            if not self.config.is_admin(event.sender_id):
                await event.respond("❌ Access denied.")
                return
            
            await event.respond("📄 Please send a txt file with filename:url pairs for batch upload.")
        
        @self.client.on(events.NewMessage(pattern='/txt_links'))
        async def txt_links_handler(event):
            if not self.config.is_admin(event.sender_id):
                await event.respond("❌ Access denied.")
                return
            
            await event.respond("📄 Please send a txt file with filename:url pairs. Results will be provided as a downloadable txt file.")
        
        @self.client.on(events.NewMessage)
        async def message_handler(event):
            if not self.config.is_admin(event.sender_id):
                return
            
            # Skip if it's a command
            if event.text and event.text.startswith('/'):
                return
            
            try:
                # Handle file uploads
                if event.file:
                    await self.handle_file_upload(event)
                # Handle URL messages
                elif event.text and ('http://' in event.text or 'https://' in event.text):
                    await self.handle_url_upload(event)
                else:
                    # Ignore other text messages
                    pass
                    
            except Exception as e:
                logger.error(f"Error in message handler: {e}")
                await event.respond(f"❌ Error processing your request: {str(e)}")
    
    async def handle_file_upload(self, event):
        """Handle file upload from Telegram"""
        try:
            # Get file info
            file = event.file
            if not file:
                await event.respond("❌ No file detected.")
                return
            
            # Get original filename
            original_filename = "unknown_file"
            if file.name:
                original_filename = file.name
            elif hasattr(file, 'attributes'):
                for attr in file.attributes:
                    if isinstance(attr, DocumentAttributeFilename):
                        original_filename = attr.file_name
                        break
            
            # Normalize filename for Unicode/Hindi support
            safe_filename = self.normalize_filename(original_filename)
            
            # Check if it's a txt file for batch processing
            if original_filename.lower().endswith('.txt'):
                # Download and read txt file
                progress_msg = await event.respond("📥 Downloading txt file...")
                
                with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                    await self.client.download_file(file, temp_file.name)
                    
                    # Read content with proper encoding
                    try:
                        with open(temp_file.name, 'r', encoding='utf-8') as f:
                            content = f.read()
                    except UnicodeDecodeError:
                        with open(temp_file.name, 'r', encoding='utf-8-sig') as f:
                            content = f.read()
                    
                    os.unlink(temp_file.name)
                
                await progress_msg.edit("📋 Parsing txt file...")
                
                # Parse txt file content
                files_to_upload = self.parse_txt_file_content(content)
                
                if not files_to_upload:
                    await progress_msg.edit("❌ No valid filename:url pairs found in txt file.\n\nFormat should be:\nfilename1.ext : http://url1\nfilename2.ext : http://url2")
                    return
                
                await progress_msg.edit(f"🔄 Found {len(files_to_upload)} files to upload. Starting batch upload...")
                
                # Check if this was triggered by /txt_links command context
                return_as_txt = False
                if hasattr(event, '_txt_links_mode'):
                    return_as_txt = True
                
                # Process batch upload
                result = await self.process_txt_file_upload(files_to_upload, return_as_txt)
                await progress_msg.edit(result)
                
            else:
                # Regular file upload
                progress_msg = await event.respond("📤 Uploading file...")
                
                # Create temp file
                with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                    await self.client.download_file(file, temp_file.name)
                    
                    # Upload to GitHub
                    github_url = await self.uploader.upload_file(temp_file.name, safe_filename)
                    
                    # Clean up
                    os.unlink(temp_file.name)
                
                if github_url:
                    file_size = self.format_file_size(file.size) if file.size else ""
                    response = format_upload_complete_message(github_url, safe_filename, file_size)
                    await progress_msg.edit(response)
                else:
                    await progress_msg.edit("❌ Upload failed. Please try again.")
                    
        except Exception as e:
            logger.error(f"Error handling file upload: {e}")
            await event.respond(f"❌ Error uploading file: {str(e)}")
    
    async def handle_url_upload(self, event):
        """Handle URL upload (M3U8 or direct file URL)"""
        try:
            url = event.text.strip()
            
            # Extract filename from URL or use default
            filename = url.split('/')[-1] if '/' in url else "downloaded_file"
            if '?' in filename:
                filename = filename.split('?')[0]
            
            # Normalize filename
            safe_filename = self.normalize_filename(filename)
            
            progress_msg = await event.respond("🔄 Processing URL...")
            
            # Detect file type
            file_type = self.detect_file_type_from_url(url, filename)
            
            github_url = None
            if file_type == 'm3u8' or '.m3u8' in url.lower():
                await progress_msg.edit("📺 Detected M3U8 stream. Processing...")
                github_url = await self.uploader.upload_m3u8_from_url(url, safe_filename)
            else:
                await progress_msg.edit(f"📁 Detected {file_type} file. Downloading and uploading...")
                github_url = await self.uploader.upload_file_from_url(url, safe_filename)
            
            if github_url:
                response = format_upload_complete_message(github_url, safe_filename)
                await progress_msg.edit(response)
            else:
                await progress_msg.edit("❌ Upload failed. Please check the URL and try again.")
                
        except Exception as e:
            logger.error(f"Error handling URL upload: {e}")
            await event.respond(f"❌ Error processing URL: {str(e)}")
    
    def format_file_size(self, size_bytes: int) -> str:
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "0 B"
        
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        while size_bytes >= 1024 and i < len(size_names) - 1:
            size_bytes /= 1024.0
            i += 1
        
        return f"{size_bytes:.1f} {size_names[i]}"
    
    async def start(self):
        """Start the bot"""
        logger.info("Starting Telegram bot...")
        await self.client.start(bot_token=self.config.telegram_bot_token)
        
        me = await self.client.get_me()
        logger.info(f"Bot started successfully: @{me.username}")
        
        await self.client.run_until_disconnected()
    
    async def stop(self):
        """Stop the bot"""
        logger.info("Stopping bot...")
        await self.client.disconnect()

# Global bot instance
bot = TelegramBot()

async def main():
    """Main function"""
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())
