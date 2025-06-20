
import logging
from telegram import Update
from telegram.ext import ContextTypes
from bot_txt_handler import BotTxtHandler
from config import BotConfig

logger = logging.getLogger(__name__)

class MainBotIntegration:
    def __init__(self, config: BotConfig):
        self.config = config
        self.txt_handler = BotTxtHandler(config)
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Main message handler - returns True if message was handled"""
        try:
            # Handle txt help command
            if await self.txt_handler.handle_txt_help(update, context):
                return True
            
            # Handle txt file uploads
            if await self.txt_handler.handle_txt_file(update, context):
                return True
            
            # Message not handled by our integration
            return False
            
        except Exception as e:
            logger.error(f"Error in main bot integration: {e}")
            return False

# Global instance to be imported by bot.py
bot_integration = None

def initialize_bot_integration(config: BotConfig):
    """Initialize the bot integration with config"""
    global bot_integration
    bot_integration = MainBotIntegration(config)
    return bot_integration
