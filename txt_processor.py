
import logging
import re
from typing import Dict, List, Tuple, Optional
import tempfile
import os

logger = logging.getLogger(__name__)

class TxtFileProcessor:
    def __init__(self):
        self.supported_formats = [
            r'^(.+?)\s*:\s*(.+)$',  # file_name : file_url
            r'^(.+?)\s*-\s*(.+)$',  # file_name - file_url
            r'^(.+?)\s*=\s*(.+)$',  # file_name = file_url
        ]
    
    def is_txt_upload_format(self, content: str) -> bool:
        """Check if the content is in the expected txt upload format"""
        lines = content.strip().split('\n')
        if len(lines) < 1:
            return False
        
        valid_lines = 0
        for line in lines:
            line = line.strip()
            if not line:  # Skip empty lines
                continue
            
            # Check if line matches any supported format
            for pattern in self.supported_formats:
                if re.match(pattern, line):
                    valid_lines += 1
                    break
        
        # Consider it a txt upload format if at least 50% of non-empty lines match
        non_empty_lines = len([l for l in lines if l.strip()])
        return valid_lines >= max(1, non_empty_lines * 0.5)
    
    def parse_txt_content(self, content: str) -> List[Tuple[str, str]]:
        """Parse txt content and extract file_name : file_url pairs"""
        results = []
        lines = content.strip().split('\n')
        
        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:  # Skip empty lines
                continue
            
            parsed = False
            for pattern in self.supported_formats:
                match = re.match(pattern, line)
                if match:
                    file_name = match.group(1).strip()
                    file_url = match.group(2).strip()
                    
                    if file_name and file_url:
                        results.append((file_name, file_url))
                        logger.info(f"Parsed line {line_num}: {file_name} -> {file_url}")
                        parsed = True
                        break
            
            if not parsed:
                logger.warning(f"Could not parse line {line_num}: {line}")
        
        logger.info(f"Successfully parsed {len(results)} file entries")
        return results
    
    def create_result_txt(self, results: List[Tuple[str, str, str]]) -> str:
        """Create result txt content with file_name : github_url format"""
        lines = []
        for file_name, original_url, github_url in results:
            lines.append(f"{file_name} : {github_url}")
        
        content = '\n'.join(lines)
        logger.info(f"Created result txt with {len(results)} entries")
        return content
    
    def create_temp_txt_file(self, content: str, filename: str = "github_links.txt") -> str:
        """Create a temporary txt file with the given content"""
        try:
            temp_dir = tempfile.mkdtemp()
            temp_file_path = os.path.join(temp_dir, filename)
            
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"Created temporary txt file: {temp_file_path}")
            return temp_file_path
        except Exception as e:
            logger.error(f"Error creating temporary txt file: {e}")
            raise
    
    def format_txt_processing_message(self, 
                                    original_count: int, 
                                    successful_count: int, 
                                    failed_count: int,
                                    result_file_url: str) -> str:
        """Format the message for txt file processing results"""
        message = f"📝 Txt File Processing Complete!\n\n"
        message += f"📊 Processing Summary:\n"
        message += f"   • Total files found: {original_count}\n"
        message += f"   • Successfully uploaded: {successful_count}\n"
        
        if failed_count > 0:
            message += f"   • Failed uploads: {failed_count}\n"
        
        message += f"\n📎 Result File:\n"
        message += f"🔗 Download your updated links: {result_file_url}\n"
        message += f"\n💡 The result file contains all GitHub URLs in the same format as your input."
        
        return message

# Global instance
txt_processor = TxtFileProcessor()

def is_txt_upload_request(content: str) -> bool:
    """Check if content is a txt upload request"""
    return txt_processor.is_txt_upload_format(content)

def parse_txt_upload_content(content: str) -> List[Tuple[str, str]]:
    """Parse txt upload content"""
    return txt_processor.parse_txt_content(content)

def create_txt_result_file(results: List[Tuple[str, str, str]], filename: str = "github_links.txt") -> str:
    """Create result txt file and return path"""
    content = txt_processor.create_result_txt(results)
    return txt_processor.create_temp_txt_file(content, filename)

def format_txt_result_message(original_count: int, successful_count: int, failed_count: int, result_file_url: str) -> str:
    """Format txt processing result message"""
    return txt_processor.format_txt_processing_message(original_count, successful_count, failed_count, result_file_url)
