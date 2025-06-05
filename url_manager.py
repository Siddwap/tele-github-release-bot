
import logging
from typing import Dict, Optional
from proxy_service import ProxyService
from config import BotConfig

logger = logging.getLogger(__name__)

class URLManager:
    def __init__(self, config: BotConfig):
        self.config = config
        self.proxy_service = ProxyService(
            secret_key=getattr(config, 'proxy_secret_key', 'telegram_bot_proxy_secret'),
            proxy_domain=getattr(config, 'proxy_domain', 'localhost:5000')
        )
        self.proxy_enabled = getattr(config, 'proxy_enabled', True)
    
    def process_upload_result(self, github_url: str, filename: str) -> Dict[str, str]:
        """Process GitHub upload result and return both URLs"""
        result = {
            'original_url': github_url,
            'filename': filename,
            'proxy_enabled': self.proxy_enabled
        }
        
        if self.proxy_enabled:
            try:
                proxy_url = self.proxy_service.encode_url(github_url, filename)
                result['proxy_url'] = proxy_url
                result['has_proxy'] = True
            except Exception as e:
                logger.error(f"Failed to generate proxy URL: {e}")
                result['proxy_url'] = github_url
                result['has_proxy'] = False
        else:
            result['proxy_url'] = github_url
            result['has_proxy'] = False
        
        return result
    
    def format_download_message(self, url_data: Dict[str, str], file_size: str = "") -> str:
        """Format the download message with both URLs"""
        filename = url_data['filename']
        original_url = url_data['original_url']
        
        message = f"✅ Upload Complete!\n\n"
        message += f"📁 File: {filename}\n"
        
        if file_size:
            message += f"📊 Size: {file_size}\n"
        
        message += f"\n🔗 Download URLs:\n"
        
        if url_data.get('has_proxy', False):
            proxy_url = url_data['proxy_url']
            message += f"🌐 Proxy URL: {proxy_url}\n"
            message += f"📎 Direct URL: {original_url}\n"
            message += f"\n💡 Use proxy URL for privacy, direct URL for maximum speed"
        else:
            message += f"📎 Download URL: {original_url}\n"
            if not url_data.get('proxy_enabled', True):
                message += f"ℹ️ Proxy service disabled"
        
        return message
    
    def get_original_url(self, proxy_url: str) -> Optional[str]:
        """Extract original GitHub URL from proxy URL if valid"""
        if not self.proxy_enabled:
            return None
            
        try:
            # Extract proxy ID from URL
            if '/file/' in proxy_url:
                parts = proxy_url.split('/file/')
                if len(parts) == 2:
                    file_part = parts[1]
                    if '/' in file_part:
                        filename, proxy_id = file_part.split('/', 1)
                        return self.proxy_service.decode_url(proxy_id)
            
            return None
        except Exception as e:
            logger.error(f"Error extracting original URL: {e}")
            return None
    
    def create_short_link_info(self, url_data: Dict[str, str]) -> str:
        """Create a short info message for inline use"""
        if url_data.get('has_proxy', False):
            return f"🌐 Proxy + 📎 Direct URLs available"
        else:
            return f"📎 Direct URL available"
