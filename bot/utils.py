"""
Utility functions for the Telegram bot
"""
import re
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


def sanitize_filename_preserve_unicode(filename: str) -> str:
    """Sanitize filename while preserving Unicode characters like Hindi"""
    # Split filename and extension
    if '.' in filename:
        name_part = '.'.join(filename.split('.')[:-1])
        extension = filename.split('.')[-1]
    else:
        name_part = filename
        extension = ''
    
    # Only replace truly problematic characters, preserve Unicode
    # Remove: < > : " | ? * \ / and control characters
    name_part = re.sub(r'[<>:"|?*\\/\x00-\x1f\x7f]', '_', name_part)
    
    # Replace multiple spaces with single space
    name_part = re.sub(r'\s+', ' ', name_part)
    
    # Remove leading/trailing spaces and dots
    name_part = name_part.strip(' .')
    
    # Ensure we have some content
    if not name_part:
        name_part = 'file'
    
    # Reconstruct filename with extension
    if extension:
        return f"{name_part}.{extension}"
    else:
        return name_part


def sanitize_filename(filename: str) -> str:
    """Legacy sanitize method - kept for compatibility"""
    return sanitize_filename_preserve_unicode(filename)


def detect_file_type_from_url(url: str) -> str:
    """Detect file type from URL"""
    url_lower = url.lower()
    
    # Remove query parameters for extension detection
    clean_url = url_lower.split('?')[0]
    
    # Video formats
    if any(ext in clean_url for ext in ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm']):
        return 'video'
    elif any(ext in clean_url for ext in ['.m3u8', '.m3u']):
        return 'm3u8'
    # Audio formats
    elif any(ext in clean_url for ext in ['.mp3', '.wav', '.flac', '.aac', '.ogg']):
        return 'audio'
    # Document formats
    elif any(ext in clean_url for ext in ['.pdf', '.doc', '.docx', '.txt', '.rtf']):
        return 'document'
    # Image formats
    elif any(ext in clean_url for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']):
        return 'image'
    # Archive formats
    elif any(ext in clean_url for ext in ['.zip', '.rar', '.7z', '.tar', '.gz']):
        return 'archive'
    else:
        return 'unknown'


def get_file_extension_from_url(url: str) -> str:
    """Extract file extension from URL"""
    clean_url = url.split('?')[0]  # Remove query parameters
    if '.' in clean_url:
        return clean_url.split('.')[-1].lower()
    return ''


def is_url(text: str) -> bool:
    """Check if text is a valid URL"""
    if not text:
        return False
    return text.startswith(('http://', 'https://')) and len(text) > 8


def is_youtube_url(text: str) -> bool:
    """Check if text is a YouTube URL"""
    if not text:
        return False
    youtube_patterns = [
        'youtube.com/watch',
        'youtu.be/',
        'm.youtube.com/watch',
        'youtube.com/shorts',
        'www.youtube.com/live,
        'youtube.com/live'
    ]
    return any(pattern in text.lower() for pattern in youtube_patterns)


def format_size(size: int) -> str:
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


async def parse_txt_file_content(content: str, detect_file_type_func, get_extension_func) -> List[Dict]:
    """Parse txt file content and extract filename:url pairs"""
    lines = content.strip().split('\n')
    parsed_items = []
    
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith('#'):  # Skip empty lines and comments
            continue
        
        if ':' in line:
            # Split on first colon to handle URLs with colons
            parts = line.split(':', 1)
            if len(parts) == 2:
                filename = parts[0].strip()
                url = parts[1].strip()
                
                if filename and url:
                    # Detect file type from URL
                    file_type = detect_file_type_func(url)
                    
                    # If filename doesn't have extension, try to add one from URL
                    if '.' not in filename:
                        ext = get_extension_func(url)
                        if ext:
                            filename = f"{filename}.{ext}"
                    
                    parsed_items.append({
                        'filename': filename,
                        'url': url,
                        'file_type': file_type,
                        'line_number': line_num
                    })
                else:
                    logger.warning(f"Invalid format on line {line_num}: {line}")
            else:
                logger.warning(f"Invalid format on line {line_num}: {line}")
        else:
            # Treat as URL only, generate filename
            if line.startswith('http'):
                url = line
                filename = url.split('/')[-1] or f"file_{line_num}"
                if '?' in filename:
                    filename = filename.split('?')[0]
                
                file_type = detect_file_type_func(url)
                
                # Add extension if missing
                if '.' not in filename:
                    ext = get_extension_func(url)
                    if ext:
                        filename = f"{filename}.{ext}"
                    else:
                        filename = f"{filename}.bin"
                
                parsed_items.append({
                    'filename': filename,
                    'url': url,
                    'file_type': file_type,
                    'line_number': line_num
                })
            else:
                logger.warning(f"Invalid URL on line {line_num}: {line}")
    
    return parsed_items


async def create_result_txt_file(results: List[Dict], original_filename: str) -> str:
    """Create a txt file with the upload results"""
    from datetime import datetime
    
    content_lines = []
    content_lines.append(f"# Upload Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    content_lines.append(f"# Original file: {original_filename}")
    content_lines.append("")
    
    for result in results:
        if result['success']:
            content_lines.append(f"{result['filename']} : {result['github_url']}")
        else:
            content_lines.append(f"# FAILED: {result['filename']} - {result['error']}")
    
    return '\n'.join(content_lines)
