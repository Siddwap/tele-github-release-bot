
"""
Monkey patch module to override bot response formatting.
Import this module in your bot to automatically use proxy URLs.
"""

import logging
from bot_integration import get_upload_response_with_proxy

logger = logging.getLogger(__name__)

def patch_upload_response():
    """
    Monkey patch common response formatting functions to use proxy URLs.
    Call this function early in your bot initialization.
    """
    try:
        # Try to patch common function names that might be used in the bot
        import sys
        
        # Create a mock module with our functions
        class ProxyResponseModule:
            @staticmethod
            def format_upload_message(github_url, filename, file_size=""):
                return get_upload_response_with_proxy(github_url, filename, file_size)
            
            @staticmethod
            def format_response(github_url, filename, file_size=""):
                return get_upload_response_with_proxy(github_url, filename, file_size)
            
            @staticmethod
            def get_download_message(github_url, filename, file_size=""):
                return get_upload_response_with_proxy(github_url, filename, file_size)
        
        # Add to sys.modules so it can be imported
        sys.modules['proxy_response'] = ProxyResponseModule()
        
        logger.info("Bot response patching successful")
        return True
        
    except Exception as e:
        logger.error(f"Failed to patch bot response: {e}")
        return False

# Auto-patch when imported
patch_upload_response()

# Export the main function for direct use
format_upload_response = get_upload_response_with_proxy
