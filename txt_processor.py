
import re
import logging
from typing import List, Tuple, Optional
import os
import tempfile

logger = logging.getLogger(__name__)

def is_txt_upload_request(message_text: str) -> bool:
    """
    Check if the message contains txt upload format.
    Format: filename : url or filename - url or filename = url
    """
    if not message_text or len(message_text.strip()) < 10:
        return False
    
    lines = message_text.strip().split('\n')
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
    
    # Consider it a txt upload if at least 2 valid lines or more than 50% of lines are valid
    total_non_empty_lines = len([l for l in lines if l.strip()])
    return valid_lines >= 2 or (total_non_empty_lines > 0 and valid_lines / total_non_empty_lines > 0.5)

def parse_txt_upload_content(message_text: str) -> List[Tuple[str, str]]:
    """
    Parse txt upload content and return list of (filename, url) tuples.
    Preserves Unicode characters including Hindi text in filenames.
    """
    file_entries = []
    lines = message_text.strip().split('\n')
    
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
