
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
    Handle bot message - checks for txt upload format and processes accordingly.
    This is the main function bots should use for message handling.
    
    Returns:
    - String response if message was handled (txt upload or help)
    - None if message should be processed normally
    """
    try:
        logger.info(f"Checking message for txt upload: {message_text[:100]}...")
        
        # Check for help commands first
        help_commands = ['/txt_help', '!txt_help', '#txt_help', 'txt_help', '/txthelp', '!txthelp']
        if any(cmd.lower() in message_text.lower() for cmd in help_commands):
            logger.info("Returning txt help message")
            return get_txt_help()
        
        # Check if it's a txt upload request (requires command)
        if is_txt_upload_message(message_text):
            logger.info("Detected txt upload command, processing...")
            response = await handle_txt_upload_message(github_uploader, message_text)
            logger.info("Txt upload processing completed")
            return response
        
        # Return None to indicate normal processing should continue
        logger.info("Message is not a txt upload request, continuing normal processing")
        return None
        
    except Exception as e:
        logger.error(f"Error in bot message handling: {e}", exc_info=True)
        return f"❌ Error processing your message: {str(e)}\n\nUse `/txt_help` for instructions on txt upload feature."

def check_txt_upload_format(message_text: str) -> bool:
    """
    Check if message is in txt upload format (requires command).
    Use this before processing messages normally.
    """
    result = is_txt_upload_message(message_text)
    logger.info(f"Txt upload format check result: {result}")
    return result

def get_txt_upload_help_message() -> str:
    """
    Get help message for txt upload feature.
    """
    return get_txt_help()

# For direct import compatibility
format_response = get_upload_response_with_proxy
