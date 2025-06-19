
import logging
import asyncio
from typing import Optional
from txt_processor import (
    is_txt_upload_request, 
    parse_txt_upload_content, 
    create_txt_result_file, 
    format_txt_result_message
)
from bulk_uploader import process_txt_bulk_upload
from github_uploader import GitHubUploader
from bot_integration import get_upload_response_with_proxy

logger = logging.getLogger(__name__)

class TxtBotIntegration:
    def __init__(self, github_uploader: GitHubUploader):
        self.github_uploader = github_uploader
    
    def should_process_as_txt_upload(self, message_text: str) -> bool:
        """Check if the message should be processed as txt upload"""
        return is_txt_upload_request(message_text)
    
    async def process_txt_upload_message(self, message_text: str) -> str:
        """Process a txt upload message and return response"""
        try:
            logger.info("Processing txt upload message")
            
            # Parse the txt content
            file_entries = parse_txt_upload_content(message_text)
            
            if not file_entries:
                return ("❌ No valid file entries found in your message.\n\n"
                       "Please use the format:\n"
                       "file_name1 : file_url1\n"
                       "file_name2 : file_url2\n"
                       "etc.\n\n"
                       "Supported separators: ' : ', ' - ', ' = '\n"
                       "Unicode filenames (including Hindi) are fully supported!")
            
            logger.info(f"Found {len(file_entries)} file entries to process")
            
            # Show processing message info
            logger.info(f"🔄 Processing {len(file_entries)} files from your txt input...")
            
            # Process bulk upload
            results = await process_txt_bulk_upload(self.github_uploader, file_entries)
            
            # Count results
            successful_results = [(name, orig, github) for name, orig, github in results if github]
            failed_count = len(results) - len(successful_results)
            
            if not successful_results:
                return ("❌ All file uploads failed.\n\n"
                       "Please check that your URLs are accessible and files are not too large (100MB limit).\n"
                       "Make sure the URLs are direct download links.")
            
            # Create result txt file with Unicode support
            result_file_path = create_txt_result_file(successful_results, "github_links.txt")
            
            # Upload result file to GitHub
            result_github_url = self.github_uploader.upload_file(result_file_path, "github_links.txt")
            
            # Get formatted response with proxy URL if available
            result_response = get_upload_response_with_proxy(result_github_url, "github_links.txt")
            
            # Format final message
            summary_msg = format_txt_result_message(
                len(file_entries), 
                len(successful_results), 
                failed_count, 
                result_github_url
            )
            
            return f"{summary_msg}\n\n{result_response}"
            
        except Exception as e:
            logger.error(f"Error processing txt upload: {e}")
            return (f"❌ Error processing your txt upload: {str(e)}\n\n"
                   f"Please check your file format and try again.")
    
    def get_txt_upload_help(self) -> str:
        """Get help message for txt upload format"""
        return (
            "📝 **Txt Upload Format Help**\n\n"
            "To upload multiple files from a txt list, use this format:\n\n"
            "```\n"
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
            "video1.mp4 : https://example.com/video1.mp4\n"
            "गणित_पुस्तक.pdf : https://example.com/math_book.pdf\n"
            "image.jpg : https://example.com/image.jpg\n"
            "```\n\n"
            "The bot will download all files, upload them to GitHub with preserved Unicode filenames, and send you back a txt file with the GitHub URLs!"
        )

# Global instance function
def create_txt_bot_integration(github_uploader: GitHubUploader) -> TxtBotIntegration:
    """Create TxtBotIntegration instance"""
    return TxtBotIntegration(github_uploader)

# Easy-to-use functions for bot integration
async def handle_txt_upload_message(github_uploader: GitHubUploader, message_text: str) -> Optional[str]:
    """Handle txt upload message - returns response if it's a txt upload, None otherwise"""
    integration = TxtBotIntegration(github_uploader)
    
    if integration.should_process_as_txt_upload(message_text):
        return await integration.process_txt_upload_message(message_text)
    
    return None

def is_txt_upload_message(message_text: str) -> bool:
    """Check if message is a txt upload request"""
    return is_txt_upload_request(message_text)

def get_txt_help() -> str:
    """Get txt upload help message"""
    integration = TxtBotIntegration(None)
    return integration.get_txt_upload_help()
