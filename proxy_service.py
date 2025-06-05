
import base64
import hashlib
import hmac
import time
import logging
from typing import Optional, Dict, Tuple
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)

class ProxyService:
    def __init__(self, secret_key: str = "default_secret_key", proxy_domain: str = "localhost:5000"):
        self.secret_key = secret_key.encode()
        self.proxy_domain = proxy_domain
        
    def encode_url(self, github_url: str, filename: str) -> str:
        """Encode GitHub URL into a clean proxy URL"""
        try:
            # Create payload with URL and timestamp
            timestamp = str(int(time.time()))
            payload = f"{github_url}|{timestamp}"
            
            # Encode payload
            encoded_payload = base64.urlsafe_b64encode(payload.encode()).decode().rstrip('=')
            
            # Create signature for security
            signature = hmac.new(
                self.secret_key,
                encoded_payload.encode(),
                hashlib.sha256
            ).hexdigest()[:16]
            
            # Create clean filename-based identifier
            clean_filename = quote(filename.replace(' ', '_'))
            proxy_id = f"{encoded_payload}.{signature}"
            
            return f"https://{self.proxy_domain}/file/{clean_filename}/{proxy_id}"
            
        except Exception as e:
            logger.error(f"Error encoding URL: {e}")
            return github_url  # Fallback to original URL
    
    def decode_url(self, proxy_id: str) -> Optional[str]:
        """Decode proxy URL back to original GitHub URL"""
        try:
            if '.' not in proxy_id:
                return None
                
            encoded_payload, signature = proxy_id.rsplit('.', 1)
            
            # Verify signature
            expected_signature = hmac.new(
                self.secret_key,
                encoded_payload.encode(),
                hashlib.sha256
            ).hexdigest()[:16]
            
            if not hmac.compare_digest(signature, expected_signature):
                logger.warning("Invalid signature in proxy URL")
                return None
            
            # Decode payload
            # Add padding if needed
            padding_needed = 4 - (len(encoded_payload) % 4)
            if padding_needed != 4:
                encoded_payload += '=' * padding_needed
                
            payload = base64.urlsafe_b64decode(encoded_payload).decode()
            github_url, timestamp = payload.split('|', 1)
            
            # Optional: Check if URL is not too old (e.g., 30 days)
            url_age = time.time() - int(timestamp)
            if url_age > (30 * 24 * 60 * 60):  # 30 days
                logger.warning("Proxy URL has expired")
                # Still return URL but log the warning
            
            return github_url
            
        except Exception as e:
            logger.error(f"Error decoding proxy URL: {e}")
            return None
    
    def generate_proxy_urls(self, github_url: str, filename: str) -> Dict[str, str]:
        """Generate both original and proxy URLs"""
        proxy_url = self.encode_url(github_url, filename)
        
        return {
            'original': github_url,
            'proxy': proxy_url,
            'filename': filename
        }
    
    def validate_github_url(self, url: str) -> bool:
        """Validate that URL is a GitHub release URL"""
        return (
            url.startswith('https://github.com/') and
            '/releases/download/' in url
        )
