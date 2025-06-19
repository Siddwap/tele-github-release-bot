
"""
Bot integration module for proxy URL functionality.
This module provides simple functions that can be imported and used by the main bot.
"""

import logging
import asyncio
from response_formatter import format_upload_complete_message, get_both_urls
from txt_bot_integration import handle_txt_upload_message, is_txt_upload_message, get_txt_help

logger = logging.getLogger(__name__)

def get_upload_response_with_proxy(github_url: str, filename: str, file_size: str = "") -> str:
    """
    Get formatted upload response with both original and proxy URLs.
    This is the main function the bot should use.
    """
    try:
        logger.info(f"Getting upload response for {filename}")
        return format_upload_complete_message(github_url, filename, file_size)
    except Exception as e:
        logger.error(f"Error in bot integration: {e}")
        # Fallback to simple response
        return f"✅ Upload Complete!\n\n📁 File: {filename}\n📎 Download URL: {github_url}"

def get_url_info(github_url: str, filename: str) -> dict:
    """
    Get detailed URL information including both original and proxy URLs.
    """
    try:
        return get_both_urls(github_url, filename)
    except Exception as e:
        logger.error(f"Error getting URL info: {e}")
        return {
            'original_url': github_url,
            'filename': filename,
            'proxy_url': github_url,
            'has_proxy': False,
            'error': str(e)
        }

async def handle_bot_message(github_uploader, message_text: str) -> str:
    """
    MAIN FUNCTION FOR BOT.PY TO USE
    Handle bot message - checks for txt upload format and processes accordingly.
    This should be called BEFORE normal file processing in bot.py
    
    Returns:
    - String response if message was handled (txt upload or help)
    - None if message should be processed normally
    """
    try:
        logger.info(f"=== BOT MESSAGE HANDLER CALLED ===")
        logger.info(f"Message preview: {message_text[:200]}...")
        
        # Check for help commands first - be very explicit
        help_keywords = [
            '/txt_help', '!txt_help', '#txt_help', 'txt_help', 
            '/txthelp', '!txthelp', '/help_txt', '!help_txt'
        ]
        
        message_lower = message_text.lower().strip()
        
        for keyword in help_keywords:
            if keyword.lower() in message_lower:
                logger.info(f"=== HELP COMMAND DETECTED: {keyword} ===")
                return get_txt_help()
        
        # Check if it's a txt upload request (requires command)
        if is_txt_upload_message(message_text):
            logger.info("=== TXT UPLOAD COMMAND DETECTED ===")
            logger.info("Processing txt upload...")
            response = await handle_txt_upload_message(github_uploader, message_text)
            logger.info("=== TXT UPLOAD COMPLETED ===")
            return response
        
        # Return None to indicate normal processing should continue
        logger.info("=== MESSAGE IS NOT TXT COMMAND - CONTINUE NORMAL PROCESSING ===")
        return None
        
    except Exception as e:
        logger.error(f"=== ERROR IN BOT MESSAGE HANDLING ===: {e}", exc_info=True)
        return f"❌ Error processing your message: {str(e)}\n\nUse `/txt_help` for instructions on txt upload feature."

def check_txt_upload_format(message_text: str) -> bool:
    """
    Check if message is in txt upload format (requires command).
    Use this before processing messages normally in bot.py
    """
    result = is_txt_upload_message(message_text)
    logger.info(f"=== TXT UPLOAD FORMAT CHECK ===: {result}")
    logger.info(f"Message start: {message_text[:100]}")
    return result

def get_txt_upload_help_message() -> str:
    """
    Get help message for txt upload feature.
    """
    return get_txt_help()

# IMPORTANT: These are the main functions bot.py should use:
# 1. handle_bot_message() - Call this FIRST for every message
# 2. check_txt_upload_format() - Use to check if message is txt upload
# 3. get_txt_upload_help_message() - Get help text

# For direct import compatibility
format_response = get_upload_response_with_proxy

# Export all important functions for bot.py
__all__ = [
    'handle_bot_message',
    'check_txt_upload_format', 
    'get_txt_upload_help_message',
    'get_upload_response_with_proxy',
    'format_response'
]
