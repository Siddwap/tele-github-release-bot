
import os
from dataclasses import dataclass
from typing import Optional, List

@dataclass
class BotConfig:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_bot_token: str
    github_token: str
    github_repo: str
    github_release_tag: str
    admin_user_ids: List[int]
    log_level: str = "INFO"
    max_file_size: int = 4 * 1024 * 1024 * 1024  # 4GB
    progress_update_interval: int = 5  # Update every 5%
    
    # Proxy service configuration
    proxy_enabled: bool = True
    proxy_domain: str = "localhost:5000"
    proxy_secret_key: str = "telegram_bot_proxy_secret"
    
    @classmethod
    def from_env(cls) -> 'BotConfig':
        """Create config from environment variables"""
        # Parse admin user IDs from comma-separated string
        admin_ids_str = os.getenv('ADMIN_USER_IDS', '')
        admin_user_ids = []
        if admin_ids_str:
            try:
                admin_user_ids = [int(uid.strip()) for uid in admin_ids_str.split(',') if uid.strip()]
            except ValueError:
                raise ValueError("ADMIN_USER_IDS must be comma-separated integers")
        
        return cls(
            telegram_api_id=int(os.getenv('TELEGRAM_API_ID', 0)),
            telegram_api_hash=os.getenv('TELEGRAM_API_HASH', ''),
            telegram_bot_token=os.getenv('TELEGRAM_BOT_TOKEN', ''),
            github_token=os.getenv('GITHUB_TOKEN', ''),
            github_repo=os.getenv('GITHUB_REPO', ''),
            github_release_tag=os.getenv('GITHUB_RELEASE_TAG', ''),
            admin_user_ids=admin_user_ids,
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            proxy_enabled=os.getenv('PROXY_ENABLED', 'true').lower() == 'true',
            proxy_domain=os.getenv('PROXY_DOMAIN', 'localhost:5000'),
            proxy_secret_key=os.getenv('PROXY_SECRET_KEY', 'telegram_bot_proxy_secret'),
        )
    
    def validate(self) -> None:
        """Validate configuration"""
        required_fields = [
            'telegram_api_id', 'telegram_api_hash', 'telegram_bot_token',
            'github_token', 'github_repo', 'github_release_tag'
        ]
        
        for field in required_fields:
            value = getattr(self, field)
            if not value:
                raise ValueError(f"Missing required configuration: {field}")
        
        if self.telegram_api_id == 0:
            raise ValueError("Invalid TELEGRAM_API_ID")
        
        if not self.admin_user_ids:
            raise ValueError("At least one admin user ID must be specified in ADMIN_USER_IDS")
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user ID is in admin list"""
        return user_id in self.admin_user_ids
