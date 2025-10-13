"""
Queue management for handling multiple uploads
"""
import logging
import os
import tempfile
import time
from typing import Dict, List
from collections import deque
from telethon.tl.types import DocumentAttributeFilename
from bot.utils import sanitize_filename_preserve_unicode, create_result_txt_file
from bot.download_handlers import download_from_url_streaming_with_progress, download_telegram_file_streaming, download_from_url_streaming
from bot.upload_handlers import upload_to_github_streaming, upload_to_github_streaming_with_progress

logger = logging.getLogger(__name__)


class QueueManager:
    """Manages upload queues for different users"""
    
    def __init__(self, bot):
        self.bot = bot
        self.upload_queues: Dict[int, deque] = {}
        self.processing_queues: Dict[int, bool] = {}
    
    async def add_to_queue(self, user_id: int, upload_item: dict):
        """Add upload item to user's queue"""
        if self.bot.should_stop:
            return
        
        if user_id not in self.upload_queues:
            self.upload_queues[user_id] = deque()
        
        self.upload_queues[user_id].append(upload_item)
        await self.process_queue(user_id)
    
    async def process_queue(self, user_id: int):
        """Process upload queue for a user"""
        if self.bot.should_stop or (user_id in self.processing_queues and self.processing_queues[user_id]):
            return
        
        if user_id not in self.upload_queues or not self.upload_queues[user_id]:
            return
        
        self.processing_queues[user_id] = True
        
        try:
            total_items = len(self.upload_queues[user_id])
            current_item = 0
            
            while self.upload_queues[user_id] and not self.bot.should_stop:
                current_item += 1
                upload_item = self.upload_queues[user_id].popleft()
                remaining_items = len(self.upload_queues[user_id])
                
                filename = upload_item.get('filename', upload_item.get('original_filename', 'Unknown File'))
                
                self.bot.active_uploads[user_id] = {
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
            if user_id in self.bot.active_uploads:
                del self.bot.active_uploads[user_id]
    
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
            f"📊 **Size:** {self.bot.format_size(file_size)}\n"
            f"📋 **Remaining:** {remaining} files\n"
            f"⏳ Starting..."
        )
        
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            try:
                await download_telegram_file_streaming(
                    self.bot.client, document, temp_file, progress_msg, filename,
                    self.bot.format_size, self.upload_queues, self.bot.should_stop,
                    current_item, total_items
                )
                
                await upload_to_github_streaming(
                    self.bot.github_uploader, temp_file.name, filename, file_size, progress_msg,
                    self.bot.format_size, self.upload_queues, self.bot.should_stop,
                    current_item, total_items
                )
                
                remaining = len(self.upload_queues.get(user_id, []))
                queue_text = f"\n\n📋 **Queue:** {remaining} files remaining" if remaining > 0 else ""
                
                download_url = f"https://github.com/{self.bot.config.github_repo}/releases/download/{self.bot.config.github_release_tag}/{filename}"
                
                await progress_msg.edit(
                    f"✅ **Upload Complete!** ({current_item}/{total_items})\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.bot.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}{queue_text}"
                )
                
            except Exception as e:
                logger.error(f"Error uploading file: {e}")
                await progress_msg.edit(f"❌ **Upload Failed** ({current_item}/{total_items})\n\nError: {str(e)}")
            finally:
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
        
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            try:
                file_size = await download_from_url_streaming(
                    url, temp_file, progress_msg, filename,
                    self.bot.format_size, self.upload_queues, self.bot.should_stop,
                    self.bot.add_active_session, self.bot.remove_active_session,
                    current_item, total_items
                )
                
                await upload_to_github_streaming(
                    self.bot.github_uploader, temp_file.name, filename, file_size, progress_msg,
                    self.bot.format_size, self.upload_queues, self.bot.should_stop,
                    current_item, total_items
                )
                
                remaining = len(self.upload_queues.get(user_id, []))
                queue_text = f"\n\n📋 **Queue:** {remaining} files remaining" if remaining > 0 else ""
                
                download_url = f"https://github.com/{self.bot.config.github_repo}/releases/download/{self.bot.config.github_release_tag}/{filename}"
                
                await progress_msg.edit(
                    f"✅ **Upload Complete!** ({current_item}/{total_items})\n\n"
                    f"📁 **File:** `{filename}`\n"
                    f"📊 **Size:** {self.bot.format_size(file_size)}\n"
                    f"🔗 **Download URL:**\n{download_url}{queue_text}"
                )
                
            except Exception as e:
                logger.error(f"Error processing URL: {e}")
                await progress_msg.edit(f"❌ **Upload Failed** ({current_item}/{total_items})\n\nError: {str(e)}")
            finally:
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
            if self.bot.should_stop:
                break
            
            try:
                with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                    try:
                        file_size = await download_from_url_streaming_with_progress(
                            item['url'], temp_file, status_msg, item['filename'],
                            self.bot.format_size, self.bot.should_stop, i, total_items
                        )
                        
                        sanitized_filename = sanitize_filename_preserve_unicode(item['filename'])
                        
                        download_url = await upload_to_github_streaming_with_progress(
                            self.bot.github_uploader, temp_file.name, sanitized_filename, file_size,
                            status_msg, self.bot.format_size, self.bot.should_stop, i, total_items
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
        
        # Create and send result file
        try:
            result_content = await create_result_txt_file(results, original_filename)
            result_filename = f"results_{original_filename.replace('.txt', '')}_{int(time.time())}.txt"
            
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False, encoding='utf-8') as result_file:
                result_file.write(result_content)
                result_file.flush()
                
                try:
                    successful = sum(1 for r in results if r['success'])
                    failed = total_items - successful
                    
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
