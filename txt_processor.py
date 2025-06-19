
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
    
    # Check for specific command prefixes
    command_prefixes = ['/txt_upload', '!txt_upload', '#txt_upload', 'txt_upload:', '/txtupload', '!txtupload']
    
    first_line = message_text.strip().split('\n')[0].lower()
    has_command = any(first_line.startswith(prefix.lower()) for prefix in command_prefixes)
    
    if not has_command:
        return False
    
    # Now check for valid file entries in the rest of the message
    lines = message_text.strip().split('\n')[1:]  # Skip the command line
    valid_lines = 0
    
    for line in lines:
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
                    valid_lines += 1
    
    # Consider it a txt upload if at least 1 valid line exists
    return valid_lines >= 1

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
                # Only sanitize dangerous characters but keep Unicode
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
    if len(safe_filename) > 200:
        name, ext = os.path.splitext(safe_filename)
        safe_filename = name[:190] + ext
    
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
        "📝 **Txt Upload Command Help**\n\n"
        "To upload multiple files from a txt list, use this command format:\n\n"
        "**Command:** `/txt_upload` (or `!txt_upload`, `#txt_upload`, `txt_upload:`)\n\n"
        "**Format:**\n"
        "```\n"
        "/txt_upload\n"
        "file_name1 : file_url1\n"
        "file_name2 : file_url2\n"
        "file_name3 : file_url3\n"
        "```\n\n"
        "**Supported separators:**\n"
        "• `filename : url`\n"
        "• `filename - url`\n"
        "• `filename = url`\n\n"
        "**Unicode Support:**\n"
        "• Hindi filenames: `पुस्तक.pdf : https://example.com/book.pdf`\n"
        "• Any Unicode characters are fully supported\n\n"
        "**Example:**\n"
        "```\n"
        "/txt_upload\n"
        "video1.mp4 : https://example.com/video1.mp4\n"
        "गणित_पुस्तक.pdf : https://example.com/math_book.pdf\n"
        "image.jpg : https://example.com/image.jpg\n"
        "```\n\n"
        "The bot will download all files, upload them to GitHub with preserved Unicode filenames, and send you back a txt file with the GitHub URLs!"
    )
