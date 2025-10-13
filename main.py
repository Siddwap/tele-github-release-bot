"""
Main Telegram Bot class - Refactored into modular architecture
"""
import asyncio
import logging
import os
import uuid
from telethon import TelegramClient, events
from dotenv import load_dotenv
from github_uploader import GitHubUploader
from config import BotConfig
from bot.utils import (
    sanitize_filename_preserve_unicode, detect_file_type_from_url,
    get_file_extension_from_url, is_url, is_youtube_url, format_size
)
from bot.queue_manager import QueueManager
from bot.youtube_handler import YouTubeHandler
from bot.message_handlers import MessageHandlers
from bot.command_handlers import CommandHandlers

load_dotenv()

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
        
        session_name = f'bot_{uuid.uuid4().hex[:8]}'
        self.client = TelegramClient(session_name, self.config.telegram_api_id, self.config.telegram_api_hash)
        self.github_uploader = GitHubUploader(self.config.github_token, self.config.github_repo, self.config.github_release_tag)
        
        self.active_uploads = {}
        self.should_stop = False
        self.active_sessions = {}
        
        # Initialize modular handlers
        self.queue_manager = QueueManager(self)
        self.youtube_handler = YouTubeHandler(self)
        self.message_handlers = MessageHandlers(self)
        self.command_handlers = CommandHandlers(self)
        
        # Utility methods
        self.sanitize_filename_preserve_unicode = sanitize_filename_preserve_unicode
        self.detect_file_type_from_url = detect_file_type_from_url
        self.get_file_extension_from_url = get_file_extension_from_url
        self.is_url = is_url
        self.is_youtube_url = is_youtube_url
        self.format_size = format_size
    
    def is_admin(self, user_id: int) -> bool:
        return self.config.is_admin(user_id)
    
    async def stop_all_processes(self):
        self.should_stop = True
        for user_id, sessions in self.active_sessions.items():
            for session in sessions:
                if not session.closed:
                    await session.close()
        self.active_sessions.clear()
        for user_id in list(self.queue_manager.upload_queues.keys()):
            self.queue_manager.upload_queues[user_id].clear()
        self.active_uploads.clear()
        logger.info("All processes stopped")
    
    async def restart_all_processes(self):
        self.should_stop = False
        logger.info("All processes restarted")
    
    def add_active_session(self, user_id: int, session):
        if user_id not in self.active_sessions:
            self.active_sessions[user_id] = []
        self.active_sessions[user_id].append(session)
    
    def remove_active_session(self, user_id: int, session):
        if user_id in self.active_sessions and session in self.active_sessions[user_id]:
            self.active_sessions[user_id].remove(session)
    
    async def start(self):
        try:
            await self.client.start(bot_token=self.config.telegram_bot_token)
            logger.info("Bot started successfully")
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
            raise
        
        # Register command handlers
        self.command_handlers.register_handlers(self.client)
        
        # Callback handler
        @self.client.on(events.CallbackQuery)
        async def callback_handler(event):
            user_id = event.sender_id
            data = event.data.decode('utf-8')
            
            if data.startswith('yt_quality_'):
                parts = data.split('_')
                quality = int(parts[2])
                callback_user_id = int(parts[3])
                
                if user_id != callback_user_id:
                    await event.answer("This button is not for you", alert=True)
                    return
                
                if user_id not in self.youtube_handler.youtube_pending:
                    await event.answer("Session expired, please send the YouTube URL again", alert=True)
                    return
                
                youtube_data = self.youtube_handler.youtube_pending[user_id]
                await event.delete()
                await event.answer()
                
                await self.youtube_handler.process_youtube_upload(
                    youtube_data['event'],
                    youtube_data['url'],
                    quality,
                    youtube_data['data']
                )
                
                del self.youtube_handler.youtube_pending[user_id]
                return
            
            elif data.startswith('yt_cancel_'):
                callback_user_id = int(data.split('_')[2])
                if user_id != callback_user_id:
                    await event.answer("This button is not for you", alert=True)
                    return
                if user_id in self.youtube_handler.youtube_pending:
                    del self.youtube_handler.youtube_pending[user_id]
                await event.delete()
                await event.answer("❌ Cancelled")
                return
            
            if not self.is_admin(user_id):
                await event.answer("Access denied", alert=True)
                return
            
            if data.startswith('list_page_'):
                page = int(data.split('_')[2])
                await self.command_handlers.send_file_list(event, page, edit=True)
                await event.answer()
            elif data == 'close_list':
                await event.delete()
                await event.answer()
        
        # Main message handler
        @self.client.on(events.NewMessage)
        async def message_handler(event):
            if event.message.text and event.message.text.startswith('/'):
                return
            
            user_id = event.sender_id
            
            if self.should_stop:
                await event.respond("🛑 **Bot is currently stopped**\n\nPlease wait for an administrator to restart the bot using /restart command.")
                return
            
            try:
                if event.message.document:
                    await self.message_handlers.handle_file_upload(event)
                    return
                
                if event.message.text:
                    text = event.message.text.strip()
                    
                    if self.is_youtube_url(text):
                        await self.youtube_handler.handle_youtube_url(event, text)
                        return
                    
                    if self.is_url(text):
                        await self.message_handlers.handle_url_upload(event)
                        return
                    
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
            await self.cleanup_session_files()
    
    async def cleanup_session_files(self):
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


async def main():
    bot = TelegramBot()
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
