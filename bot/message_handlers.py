"""
Message and file upload handlers
"""
import logging
import os
import tempfile
import time
from telethon.tl.types import DocumentAttributeFilename
from bot.utils import sanitize_filename_preserve_unicode, parse_txt_file_content

logger = logging.getLogger(__name__)


class MessageHandlers:
    """Handles incoming messages and files"""
    
    def __init__(self, bot):
        self.bot = bot
    
    async def handle_file_upload(self, event):
        """Handle file upload by adding to queue"""
        user_id = event.sender_id
        document = event.message.document
        
        filename = "unknown_file"
        for attr in document.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                filename = attr.file_name
                break
        
        file_size = document.size
        logger.info(f"Received file: {filename}, size: {file_size} bytes")
        
        if file_size > 4 * 1024 * 1024 * 1024:
            await event.respond("❌ File too large. Maximum size is 4GB.")
            return
        
        if filename.lower().endswith('.txt'):
            await self.handle_txt_file_upload(event, document, filename)
            return
        
        sanitized_filename = sanitize_filename_preserve_unicode(filename)
        if sanitized_filename != filename:
            logger.info(f"Sanitized filename: '{filename}' -> '{sanitized_filename}'")
        
        upload_item = {
            'type': 'file',
            'event': event,
            'document': document,
            'filename': sanitized_filename,
            'file_size': file_size,
            'user_id': user_id
        }
        
        queue_position = len(self.bot.queue_manager.upload_queues.get(user_id, [])) + 1
        await event.respond(f"📋 **File Queued**\n\n📁 **File:** `{sanitized_filename}`\n📊 **Size:** {self.bot.format_size(file_size)}\n🔢 **Position:** {queue_position}")
        
        await self.bot.queue_manager.add_to_queue(user_id, upload_item)
    
    async def handle_txt_file_upload(self, event, document, filename):
        """Handle TXT file upload for batch processing"""
        user_id = event.sender_id
        
        progress_msg = await event.respond("📄 **Processing TXT file...**\n⏳ Downloading and parsing...")
        
        try:
            with tempfile.NamedTemporaryFile(mode='w+b', delete=False) as temp_file:
                await self.bot.client.download_media(document, file=temp_file)
                temp_file.flush()
                
                with open(temp_file.name, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                try:
                    os.unlink(temp_file.name)
                except:
                    pass
            
            txt_items = await parse_txt_file_content(
                content,
                self.bot.detect_file_type_from_url,
                self.bot.get_file_extension_from_url
            )
            
            if not txt_items:
                await progress_msg.edit("❌ **No valid items found in TXT file**\n\nExpected format:\n`filename.ext : https://example.com/file.ext`")
                return
            
            await progress_msg.edit(
                f"✅ **TXT file parsed successfully**\n\n"
                f"📁 **File:** `{filename}`\n"
                f"📊 **Items found:** {len(txt_items)}\n"
                f"⏳ **Starting batch upload...**"
            )
            
            upload_item = {
                'type': 'txt_batch',
                'event': event,
                'txt_items': txt_items,
                'original_filename': filename,
                'user_id': user_id
            }
            
            await self.bot.queue_manager.add_to_queue(user_id, upload_item)
            
        except Exception as e:
            logger.error(f"Error processing TXT file: {e}")
            await progress_msg.edit(f"❌ **Error processing TXT file**\n\n{str(e)}")
    
    async def handle_url_upload(self, event):
        """Handle URL upload by adding to queue"""
        user_id = event.sender_id
        url = event.message.text.strip()
        
        filename = url.split('/')[-1] or f"download_{int(time.time())}"
        if '?' in filename:
            filename = filename.split('?')[0]
        
        file_type = self.bot.detect_file_type_from_url(url)
        if '.' not in filename:
            ext = self.bot.get_file_extension_from_url(url)
            if ext:
                filename = f"{filename}.{ext}"
            else:
                filename = f"{filename}.bin"
        
        sanitized_filename = sanitize_filename_preserve_unicode(filename)
        if sanitized_filename != filename:
            logger.info(f"Sanitized filename: '{filename}' -> '{sanitized_filename}'")
        
        logger.info(f"Queuing URL: {url}, detected type: {file_type}")
        
        upload_item = {
            'type': 'url',
            'event': event,
            'url': url,
            'filename': sanitized_filename,
            'user_id': user_id
        }
        
        queue_position = len(self.bot.queue_manager.upload_queues.get(user_id, [])) + 1
        await event.respond(f"📋 **URL Queued**\n\n🔗 **URL:** `{url}`\n📁 **File:** `{sanitized_filename}`\n📋 **Type:** `{file_type}`\n🔢 **Position:** {queue_position}")
        
        await self.bot.queue_manager.add_to_queue(user_id, upload_item)
