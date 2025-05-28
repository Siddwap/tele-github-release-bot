
import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class BotConfig:
    telegram_api_id: int
    telegram_api_hash: str
    telegram_bot_token: str
    github_token: str
    github_repo: str
    github_release_tag: str
    log_level: str = "INFO"
    max_file_size: int = 4 * 1024 * 1024 * 1024  # 4GB
    progress_update_interval: int = 5  # Update every 5%
    
    @classmethod
    def from_env(cls) -> 'BotConfig':
        """Create config from environment variables"""
        return cls(
            telegram_api_id=int(os.getenv('TELEGRAM_API_ID', 0)),
            telegram_api_hash=os.getenv('TELEGRAM_API_HASH', ''),
            telegram_bot_token=os.getenv('TELEGRAM_BOT_TOKEN', ''),
            github_token=os.getenv('GITHUB_TOKEN', ''),
            github_repo=os.getenv('GITHUB_REPO', ''),
            github_release_tag=os.getenv('GITHUB_RELEASE_TAG', ''),
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
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
