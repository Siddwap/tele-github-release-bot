
import re
import logging
from typing import List, Tuple, Optional
import os
import tempfile

logger = logging.getLogger(__name__)

def is_txt_upload_request(message_text: str) -> bool:
    """
    Check if the message contains txt upload format with specific command.
    Must start with /txt_upload or similar command prefix.
    """
    if not message_text or len(message_text.strip()) < 10:
        logger.info("=== MESSAGE TOO SHORT FOR TXT UPLOAD ===")
        return False
    
    # Check for specific command prefixes - be very strict
    command_prefixes = [
        '/txt_upload', '!txt_upload', '#txt_upload', 
        '/txtupload', '!txtupload', '#txtupload',
        '/txt_bulk', '!txt_bulk', '#txt_bulk'
    ]
    
    # Get the first line and check if it starts with any command
    lines = message_text.strip().split('\n')
    if not lines:
        logger.info("=== NO LINES IN MESSAGE ===")
        return False
        
    first_line = lines[0].strip().lower()
    logger.info(f"=== CHECKING FIRST LINE ===: '{first_line}'")
    
    # Must start with one of the command prefixes
    has_command = any(first_line.startswith(prefix.lower()) for prefix in command_prefixes)
    
    if not has_command:
        logger.info(f"=== NO TXT UPLOAD COMMAND FOUND ===")
        return False
    
    logger.info(f"=== TXT UPLOAD COMMAND DETECTED ===: {first_line}")
    
    # Now check for valid file entries in the rest of the message
    content_lines = lines[1:]  # Skip the command line
    valid_entries = 0
    
    for line in content_lines:
        line = line.strip()
        if not line:
            continue
            
        # Check for various separators
        if ' : ' in line or ' - ' in line or ' = ' in line:
            parts = None
            if ' : ' in line:
                parts = line.split(' : ', 1)
            elif ' - ' in line:
                parts = line.split(' - ', 1)
            elif ' = ' in line:
                parts = line.split(' = ', 1)
            
            if parts and len(parts) == 2:
                filename = parts[0].strip()
                url = parts[1].strip()
                if filename and url and url.startswith(('http://', 'https://')):
                    valid_entries += 1
                    logger.info(f"=== VALID ENTRY FOUND ===: {filename} -> {url}")
    
    logger.info(f"=== TOTAL VALID ENTRIES ===: {valid_entries}")
    return valid_entries >= 1

def parse_txt_upload_content(message_text: str) -> List[Tuple[str, str]]:
    """
    Parse txt upload content and return list of (filename, url) tuples.
    Preserves Unicode characters including Hindi text in filenames.
    Skips the command line.
    """
    file_entries = []
    lines = message_text.strip().split('\n')
    
    logger.info(f"=== PARSING TXT CONTENT ===: {len(lines)} lines")
    
    # Skip the first line (command line)
    if lines:
        lines = lines[1:]
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        logger.info(f"=== PROCESSING LINE {i+1} ===: {line}")
        
        # Try different separators
        parts = None
        separator_used = None
        
        if ' : ' in line:
            parts = line.split(' : ', 1)
            separator_used = ' : '
        elif ' - ' in line:
            parts = line.split(' - ', 1)
            separator_used = ' - '
        elif ' = ' in line:
            parts = line.split(' = ', 1)
            separator_used = ' = '
        
        if parts and len(parts) == 2:
            filename = parts[0].strip()
            url = parts[1].strip()
            
            logger.info(f"=== PARSED PARTS ===: filename='{filename}', url='{url}'")
            
            # Validate URL
            if url.startswith(('http://', 'https://')) and filename:
                # Preserve Unicode characters in filename (including Hindi)
                safe_filename = sanitize_filename_preserve_unicode(filename)
                file_entries.append((safe_filename, url))
                logger.info(f"=== ADDED ENTRY ===: {safe_filename} -> {url}")
            else:
                logger.warning(f"=== INVALID ENTRY ===: filename='{filename}', url='{url}'")
    
    logger.info(f"=== TOTAL PARSED ENTRIES ===: {len(file_entries)}")
    return file_entries

def sanitize_filename_preserve_unicode(filename: str) -> str:
    """
    Sanitize filename while preserving Unicode characters (including Hindi).
    Only removes/replaces characters that are dangerous for file systems.
    """
    # Characters that are problematic for file systems
    dangerous_chars = r'[<>:"/\\|?*\x00-\x1f]'
    
    # Replace dangerous characters with underscore
    safe_filename = re.sub(dangerous_chars, '_', filename)
    
    # Remove leading/trailing spaces and dots
    safe_filename = safe_filename.strip(' .')
    
    # Ensure filename is not empty
    if not safe_filename:
        safe_filename = "unnamed_file"
    
    # Limit length to prevent filesystem issues
    if len(safe_filename.encode('utf-8')) > 200:
        # Truncate while preserving Unicode characters
        while len(safe_filename.encode('utf-8')) > 200 and safe_filename:
            safe_filename = safe_filename[:-1]
    
    logger.info(f"=== SANITIZED FILENAME ===: '{filename}' -> '{safe_filename}'")
    return safe_filename

def create_txt_result_file(successful_results: List[Tuple[str, str, str]], output_filename: str = "github_links.txt") -> str:
    """
    Create a txt file with the results in format: filename : github_url
    Returns the path to the created file.
    """
    try:
        logger.info(f"=== CREATING RESULT FILE ===: {output_filename}")
        
        # Create temporary file
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# GitHub Upload Results\n")
            f.write("# Format: filename : github_url\n\n")
            
            for filename, original_url, github_url in successful_results:
                f.write(f"{filename} : {github_url}\n")
        
        logger.info(f"=== RESULT FILE CREATED ===: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"=== ERROR CREATING RESULT FILE ===: {e}")
        raise

def format_txt_result_message(total_files: int, successful: int, failed: int, result_github_url: str) -> str:
    """
    Format the final result message for txt upload.
    """
    message = f"🎉 **TXT UPLOAD COMPLETE!**\n\n"
    message += f"📊 **Summary:**\n"
    message += f"• Total files processed: {total_files}\n"
    message += f"• Successfully uploaded: {successful}\n"
    
    if failed > 0:
        message += f"• Failed uploads: {failed}\n"
    
    message += f"\n📄 **Results file created with all GitHub links!**"
    
    return message

def get_txt_upload_help() -> str:
    """Get help message for txt upload command"""
    return (
        "📝 **TXT UPLOAD FEATURE - Complete Guide**\n\n"
        "⚠️ **IMPORTANT:** This feature is DIFFERENT from regular file uploads!\n\n"
        
        "🚀 **What this does:**\n"
        "• Downloads multiple files from URLs you provide\n"
        "• Uploads them to GitHub with preserved filenames\n"
        "• Returns a txt file with all GitHub download links\n"
        "• Perfect for bulk uploads and Hindi filenames\n\n"
        
        "📋 **STEP-BY-STEP INSTRUCTIONS:**\n\n"
        "**Step 1:** Start with a command (REQUIRED!)\n"
        "```\n"
        "/txt_upload\n"
        "```\n"
        "Or use: `!txt_upload`, `#txt_upload`, `/txtupload`\n\n"
        
        "**Step 2:** List your files (one per line):\n"
        "```\n"
        "/txt_upload\n"
        "movie.mp4 : https://example.com/movie.mp4\n"
        "गाना.mp3 : https://example.com/hindi_song.mp3\n"
        "document.pdf : https://drive.google.com/file/d/xyz\n"
        "```\n\n"
        
        "**Supported separators:**\n"
        "• `filename : url` ← **RECOMMENDED**\n"
        "• `filename - url`\n"
        "• `filename = url`\n\n"
        
        "✅ **Perfect Example:**\n"
        "```\n"
        "/txt_upload\n"
        "Bollywood_Movie.mp4 : https://example.com/movie.mp4\n"
        "हिंदी_गाना.mp3 : https://music.com/song.mp3\n"
        "Important_Doc.pdf : https://docs.google.com/file\n"
        "```\n\n"
        
        "🎯 **Key Features:**\n"
        "• ✅ Preserves Hindi/Unicode filenames perfectly\n"
        "• ✅ Bulk processing (multiple files at once)\n"
        "• ✅ Creates result file with GitHub URLs\n"
        "• ✅ 100MB file size limit per file\n"
        "• ✅ Works with most direct download URLs\n\n"
        
        "❌ **Common Mistakes to Avoid:**\n"
        "• Forgetting the `/txt_upload` command at start\n"
        "• Using this for single regular file uploads\n"
        "• Not using proper separators (: - =)\n"
        "• Using non-direct download URLs\n\n"
        
        "🆘 **Troubleshooting:**\n"
        "• If it's not working, you probably forgot the command\n"
        "• Make sure URLs are direct download links\n"
        "• Check that filenames don't have forbidden characters\n"
        "• Each file must be under 100MB\n\n"
        
        "💡 **Pro Tips:**\n"
        "• Use `/txt_help` anytime to see this help\n"
        "• This is NOT for M3U8 playlists (different feature)\n"
        "• Perfect for downloading multiple files from cloud storage\n"
        "• Hindi filenames will be preserved exactly as typed\n\n"
        
        "Try it now with the example above! 🚀"
    )

# IMPORTANT: txt_processor.py is getting long. Consider refactoring after this update.
