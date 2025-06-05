
"""
Bot integration module for proxy URL functionality.
This module provides simple functions that can be imported and used by the main bot.
"""

import logging
from response_formatter import format_upload_complete_message, get_both_urls

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

# For direct import compatibility
format_response = get_upload_response_with_proxy
