
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
import sqlite3
from pathlib import Path
from bot import TelegramBot
from config import BotConfig
from threading import Thread

def cleanup_session_files():
    """Clean up any existing session files to prevent database locks"""
    try:
        current_dir = Path('.')
        session_files = list(current_dir.glob('*.session*'))
        for session_file in session_files:
            try:
                # Try to close any open connections
                if session_file.suffix == '.session':
                    conn = sqlite3.connect(str(session_file))
                    conn.close()
                os.remove(session_file)
                logger.info(f"Removed old session file: {session_file}")
            except Exception as e:
                logger.warning(f"Could not remove session file {session_file}: {e}")
    except Exception as e:
        logger.warning(f"Error during session cleanup: {e}")

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
    # Clean up session files on shutdown
    cleanup_session_files()
    sys.exit(0)

async def main():
    """Main entry point"""
    global logger
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Clean up any existing session files
    cleanup_session_files()
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
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
        cleanup_session_files()
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        cleanup_session_files()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        cleanup_session_files()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
