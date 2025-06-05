
import logging
from typing import Dict, Optional
from url_manager import URLManager
from config import BotConfig

logger = logging.getLogger(__name__)

class ResponseFormatter:
    def __init__(self):
        try:
            self.config = BotConfig.from_env()
            self.url_manager = URLManager(self.config)
            logger.info("ResponseFormatter initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize ResponseFormatter: {e}")
            self.url_manager = None
    
    def format_upload_response(self, github_url: str, filename: str, file_size: str = "") -> str:
        """Format the upload response with both URLs"""
        logger.info(f"Formatting upload response for: {filename}")
        
        if not self.url_manager:
            logger.warning("URL manager not available, using fallback response")
            return f"✅ Upload Complete!\n\n📁 File: {filename}\n📎 Download URL: {github_url}"
        
        try:
            # Process the upload result to get both URLs
            url_data = self.url_manager.process_upload_result(github_url, filename)
            logger.info(f"URL data generated: {url_data}")
            
            # Format the complete response message
            response = self.url_manager.format_download_message(url_data, file_size)
            logger.info(f"Formatted response: {response}")
            
            return response
            
        except Exception as e:
            logger.error(f"Error formatting upload response: {e}")
            # Fallback to simple response
            return f"✅ Upload Complete!\n\n📁 File: {filename}\n📎 Download URL: {github_url}"
    
    def get_proxy_url(self, github_url: str, filename: str) -> Optional[str]:
        """Get just the proxy URL for a GitHub URL"""
        if not self.url_manager:
            return None
            
        try:
            url_data = self.url_manager.process_upload_result(github_url, filename)
            return url_data.get('proxy_url')
        except Exception as e:
            logger.error(f"Error getting proxy URL: {e}")
            return None
    
    def validate_and_get_urls(self, github_url: str, filename: str) -> Dict[str, str]:
        """Validate and get both original and proxy URLs"""
        result = {
            'original_url': github_url,
            'filename': filename,
            'proxy_url': github_url,  # Default fallback
            'has_proxy': False,
            'error': None
        }
        
        if not self.url_manager:
            result['error'] = "Proxy service not available"
            return result
        
        try:
            url_data = self.url_manager.process_upload_result(github_url, filename)
            result.update(url_data)
            return result
        except Exception as e:
            logger.error(f"Error validating URLs: {e}")
            result['error'] = str(e)
            return result

# Global instance for easy import
response_formatter = ResponseFormatter()

def format_upload_complete_message(github_url: str, filename: str, file_size: str = "") -> str:
    """Main function to format upload completion message with both URLs"""
    logger.info(f"format_upload_complete_message called with: {filename}")
    return response_formatter.format_upload_response(github_url, filename, file_size)

def get_both_urls(github_url: str, filename: str) -> Dict[str, str]:
    """Get both original and proxy URLs"""
    return response_formatter.validate_and_get_urls(github_url, filename)

# Legacy function names for backward compatibility
def format_upload_response(github_url: str, filename: str, file_size: str = "") -> str:
    """Legacy function name for backward compatibility"""
    return format_upload_complete_message(github_url, filename, file_size)

def get_proxy_url(github_url: str, filename: str) -> Optional[str]:
    """Legacy function to get proxy URL"""
    return response_formatter.get_proxy_url(github_url, filename)
