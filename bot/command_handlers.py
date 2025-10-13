"""
Command handlers for the bot (/start, /help, /stop, /restart, etc.)
"""
import logging
from telethon import events
from telethon.tl.custom import Button

logger = logging.getLogger(__name__)


class CommandHandlers:
    """Handles all bot commands"""
    
    def __init__(self, bot):
        self.bot = bot
    
    def register_handlers(self, client):
        """Register all command handlers"""
        
        @client.on(events.NewMessage(pattern='/start'))
        async def start_handler(event):
            user_id = event.sender_id
            is_admin = self.bot.is_admin(user_id)
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
        
        @client.on(events.NewMessage(pattern='/help'))
        async def help_handler(event):
            user_id = event.sender_id
            is_admin = self.bot.is_admin(user_id)
            
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
                f"**Target Repository:** `{self.bot.config.github_repo}`\n"
                f"**Release Tag:** `{self.bot.config.github_release_tag}`"
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
        
        @client.on(events.NewMessage(pattern='/stop'))
        async def stop_handler(event):
            user_id = event.sender_id
            if not self.bot.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            await self.bot.stop_all_processes()
            await event.respond("🛑 **All processes stopped**\n\nAll uploads, queues, and active processes have been halted.\n\nUse /restart to resume operations.")
            raise events.StopPropagation
        
        @client.on(events.NewMessage(pattern='/restart'))
        async def restart_handler(event):
            user_id = event.sender_id
            if not self.bot.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            await self.bot.restart_all_processes()
            await event.respond("✅ **Bot restarted successfully**\n\nAll processes are now running normally.")
            raise events.StopPropagation
        
        @client.on(events.NewMessage(pattern='/status'))
        async def status_handler(event):
            user_id = event.sender_id
            if user_id in self.bot.active_uploads:
                upload_info = self.bot.active_uploads[user_id]
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
        
        @client.on(events.NewMessage(pattern='/queue'))
        async def queue_handler(event):
            user_id = event.sender_id
            if user_id in self.bot.queue_manager.upload_queues and self.bot.queue_manager.upload_queues[user_id]:
                queue_count = len(self.bot.queue_manager.upload_queues[user_id])
                queue_items = []
                for i, item in enumerate(list(self.bot.queue_manager.upload_queues[user_id])[:5]):
                    filename = item.get('filename', item.get('original_filename', 'Unknown File'))
                    queue_items.append(f"{i+1}. {filename}")
                
                queue_text = "\n".join(queue_items)
                if queue_count > 5:
                    queue_text += f"\n... and {queue_count - 5} more"
                
                await event.respond(f"📋 **Upload Queue ({queue_count} items):**\n\n{queue_text}")
            else:
                await event.respond("📋 Queue is empty")
            raise events.StopPropagation
        
        @client.on(events.NewMessage(pattern='/list'))
        async def list_handler(event):
            user_id = event.sender_id
            if not self.bot.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            try:
                await self.send_file_list(event, page=1)
            except Exception as e:
                await event.respond(f"❌ **Error listing files**\n\n{str(e)}")
            raise events.StopPropagation
        
        @client.on(events.NewMessage(pattern=r'/search (.+)'))
        async def search_handler(event):
            user_id = event.sender_id
            if not self.bot.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            try:
                search_term = event.pattern_match.group(1).strip().lower()
                if not search_term:
                    await event.respond("❌ **Usage:** /search <filename>")
                    return
                
                assets = await self.bot.github_uploader.list_release_assets()
                if not assets:
                    await event.respond("📂 **No files found in release**")
                    return
                
                matching_assets = []
                for i, asset in enumerate(assets, 1):
                    if search_term in asset['name'].lower():
                        matching_assets.append((i, asset))
                
                if not matching_assets:
                    await event.respond(f"🔍 **No files found matching:** `{search_term}`")
                    return
                
                response = f"🔍 **Search Results for:** `{search_term}`\n\n"
                
                for original_num, asset in matching_assets[:20]:
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
        
        @client.on(events.NewMessage(pattern=r'/delete (\d+)'))
        async def delete_handler(event):
            user_id = event.sender_id
            if not self.bot.is_admin(user_id):
                await event.respond("❌ **Access Denied**\n\nThis command is only available to administrators.")
                raise events.StopPropagation
            
            try:
                file_number = int(event.pattern_match.group(1))
                if file_number < 1:
                    await event.respond("❌ **Invalid file number**\n\nFile numbers start from 1")
                    return
                
                assets = await self.bot.github_uploader.list_release_assets()
                if not assets:
                    await event.respond("📂 **No files found in release**")
                    return
                
                if file_number > len(assets):
                    await event.respond(f"❌ **File number {file_number} not found**\n\nTotal files: {len(assets)}")
                    return
                
                target_asset = assets[file_number - 1]
                filename = target_asset['name']
                
                success = await self.bot.github_uploader.delete_asset_by_name(filename)
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
        
        @client.on(events.NewMessage(pattern=r'/rename (\d+) (.+)'))
        async def rename_handler(event):
            user_id = event.sender_id
            if not self.bot.is_admin(user_id):
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
                
                sanitized_filename = self.bot.sanitize_filename_preserve_unicode(new_filename)
                if sanitized_filename != new_filename:
                    await event.respond(f"ℹ️ **Filename sanitized:** `{new_filename}` -> `{sanitized_filename}`")
                
                assets = await self.bot.github_uploader.list_release_assets()
                if not assets:
                    await event.respond("📂 **No files found in release**")
                    return
                
                if file_number > len(assets):
                    await event.respond(f"❌ **File number {file_number} not found**\n\nTotal files: {len(assets)}")
                    return
                
                target_asset = assets[file_number - 1]
                old_filename = target_asset['name']
                
                for asset in assets:
                    if asset['name'] == sanitized_filename:
                        await event.respond(f"❌ **Filename already exists**\n\n📁 **File:** `{sanitized_filename}`")
                        return
                
                progress_msg = await event.respond(f"🔄 **Renaming file...**\n\n📁 **From:** `{old_filename}`\n📁 **To:** `{sanitized_filename}`")
                
                success = await self.bot.github_uploader.rename_asset(old_filename, sanitized_filename)
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
    
    async def send_file_list(self, event, page=1, edit=False):
        """Send file list with pagination buttons"""
        assets = await self.bot.github_uploader.list_release_assets()
        if not assets:
            if edit:
                await event.edit("📂 **No files found in release**")
            else:
                await event.respond("📂 **No files found in release**")
            return
        
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
        
        response += f"📄 **Total:** {len(assets)} files | **Page:** {page}/{total_pages}\n"
        response += f"🗑️ Use `/delete <number>` to delete a file\n"
        response += f"✏️ Use `/rename <number> <new_name>` to rename a file"
        
        buttons = []
        nav_row = []
        
        if page > 1:
            nav_row.append(Button.inline("◀️ Previous", f"list_page_{page-1}"))
        
        if page < total_pages:
            nav_row.append(Button.inline("Next ▶️", f"list_page_{page+1}"))
        
        if nav_row:
            buttons.append(nav_row)
        
        buttons.append([Button.inline("❌ Close", "close_list")])
        
        if edit:
            await event.edit(response, buttons=buttons)
        else:
            await event.respond(response, buttons=buttons)
