
#!/usr/bin/env python3
"""
Simple runner script for the Telegram bot and Flask app.
"""
import asyncio
import sys
import logging
import signal
import subprocess
import os
from bot import TelegramBot
from config import BotConfig
from threading import Thread

def start_flask():
    """Start the Flask app using gunicorn"""
    subprocess.run([
        "gunicorn", 
        "--bind", "0.0.0.0:5000",
        "--workers", "1",
        "--timeout", "120",
        "app:app"
    ])

def setup_logging():
    """Setup logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Reduce noise from aiohttp and other libraries
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('telethon').setLevel(logging.WARNING)

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger = logging.getLogger(__name__)
    logger.info("Received shutdown signal, stopping bot...")
    sys.exit(0)

async def main():
    """Main entry point"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Start Flask app with gunicorn in a separate thread
    flask_thread = Thread(target=start_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    try:
        # Load and validate configuration
        config = BotConfig.from_env()
        config.validate()
        
        logger.info("Starting Telegram GitHub Release Uploader Bot...")
        logger.info(f"Target repository: {config.github_repo}")
        logger.info(f"Release tag: {config.github_release_tag}")
        
        # Start the bot
        bot = TelegramBot()
        await bot.start()
        
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
