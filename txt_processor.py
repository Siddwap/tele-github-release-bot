
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
        return False
    
    # Check for specific command prefixes - be more strict
    command_prefixes = ['/txt_upload', '!txt_upload', '#txt_upload', '/txtupload', '!txtupload']
    
    # Get the first line and check if it starts with any command
    lines = message_text.strip().split('\n')
    if not lines:
        return False
        
    first_line = lines[0].strip().lower()
    
    # Must start with one of the command prefixes
    has_command = any(first_line.startswith(prefix.lower()) for prefix in command_prefixes)
    
    if not has_command:
        logger.info(f"No txt upload command found in first line: {first_line}")
        return False
    
    logger.info(f"Found txt upload command: {first_line}")
    
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
                    logger.info(f"Found valid entry: {filename} -> {url}")
    
    logger.info(f"Found {valid_entries} valid entries")
    return valid_entries >= 1

def parse_txt_upload_content(message_text: str) -> List[Tuple[str, str]]:
    """
    Parse txt upload content and return list of (filename, url) tuples.
    Preserves Unicode characters including Hindi text in filenames.
    Skips the command line.
    """
    file_entries = []
    lines = message_text.strip().split('\n')
    
    # Skip the first line (command line)
    if lines:
        lines = lines[1:]
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Try different separators
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
            
            # Validate URL
            if url.startswith(('http://', 'https://')) and filename:
                # Preserve Unicode characters in filename (including Hindi)
                safe_filename = sanitize_filename_preserve_unicode(filename)
                file_entries.append((safe_filename, url))
                logger.info(f"Parsed entry: {safe_filename} -> {url}")
    
    logger.info(f"Parsed {len(file_entries)} file entries from txt content")
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
    
    return safe_filename

def create_txt_result_file(successful_results: List[Tuple[str, str, str]], output_filename: str = "github_links.txt") -> str:
    """
    Create a txt file with the results in format: filename : github_url
    Returns the path to the created file.
    """
    try:
        # Create temporary file
        temp_dir = tempfile.gettempdir()
        output_path = os.path.join(temp_dir, output_filename)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# GitHub Upload Results\n")
            f.write("# Format: filename : github_url\n\n")
            
            for filename, original_url, github_url in successful_results:
                f.write(f"{filename} : {github_url}\n")
        
        logger.info(f"Created result file: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Error creating result file: {e}")
        raise

def format_txt_result_message(total_files: int, successful: int, failed: int, result_github_url: str) -> str:
    """
    Format the final result message for txt upload.
    """
    message = f"🎉 **Txt Upload Complete!**\n\n"
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
        "📝 **TXT UPLOAD FEATURE - How to Use**\n\n"
        "⚠️ **IMPORTANT:** You MUST use a command to activate this feature!\n\n"
        "**Step 1:** Start your message with one of these commands:\n"
        "• `/txt_upload`\n"
        "• `!txt_upload`\n"
        "• `#txt_upload`\n"
        "• `/txtupload`\n"
        "• `!txtupload`\n\n"
        "**Step 2:** On new lines, list your files in this format:\n"
        "```\n"
        "/txt_upload\n"
        "filename1.mp4 : https://example.com/video1.mp4\n"
        "filename2.pdf : https://example.com/document.pdf\n"
        "हिंदी_फाइल.jpg : https://example.com/hindi_image.jpg\n"
        "```\n\n"
        "**Supported separators:**\n"
        "• `filename : url` (recommended)\n"
        "• `filename - url`\n"
        "• `filename = url`\n\n"
        "**✅ Features:**\n"
        "• Supports Hindi/Unicode filenames perfectly\n"
        "• Bulk upload multiple files at once\n"
        "• Returns a txt file with all GitHub URLs\n"
        "• Preserves original filenames\n\n"
        "**❌ What NOT to do:**\n"
        "• Don't send just URLs without the command\n"
        "• Don't mix this with regular file uploads\n"
        "• Don't forget the command at the start\n\n"
        "**Example that works:**\n"
        "```\n"
        "/txt_upload\n"
        "movie.mp4 : https://drive.google.com/file/d/123/view\n"
        "गीत.mp3 : https://example.com/hindi_song.mp3\n"
        "document.pdf : https://dropbox.com/file.pdf\n"
        "```\n\n"
        "The bot will download all files, upload to GitHub with preserved names, and give you back a txt file with GitHub URLs!"
    )
