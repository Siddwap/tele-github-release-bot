
import logging
import asyncio
from typing import Optional
from txt_processor import (
    is_txt_upload_request, 
    parse_txt_upload_content, 
    create_txt_result_file, 
    format_txt_result_message,
    get_txt_upload_help
)
from bulk_uploader import process_txt_bulk_upload
from github_uploader import GitHubUploader

logger = logging.getLogger(__name__)

class TxtBotIntegration:
    def __init__(self, github_uploader: GitHubUploader):
        self.github_uploader = github_uploader
    
    def should_process_as_txt_upload(self, message_text: str) -> bool:
        """Check if the message should be processed as txt upload (requires command)"""
        result = is_txt_upload_request(message_text)
        logger.info(f"=== TXT UPLOAD CHECK ===: {result}")
        return result
    
    async def process_txt_upload_message(self, message_text: str) -> str:
        """Process a txt upload message and return response"""
        try:
            logger.info("=== STARTING TXT UPLOAD PROCESSING ===")
            
            # Parse the txt content
            file_entries = parse_txt_upload_content(message_text)
            
            if not file_entries:
                logger.warning("=== NO VALID FILE ENTRIES FOUND ===")
                return (
                    "❌ **No valid file entries found!**\n\n"
                    "**Make sure to use this format:**\n"
                    "```\n"
                    "/txt_upload\n"
                    "filename1.mp4 : https://example.com/video1.mp4\n"
                    "filename2.pdf : https://example.com/document.pdf\n"
                    "```\n\n"
                    "**Required:**\n"
                    "• Start with `/txt_upload` command\n"
                    "• Use format: `filename : url`\n"
                    "• URLs must start with http:// or https://\n\n"
                    "Use `/txt_help` for detailed instructions!"
                )
            
            logger.info(f"=== FOUND {len(file_entries)} FILE ENTRIES ===")
            
            # Process bulk upload
            logger.info("=== STARTING BULK UPLOAD ===")
            results = await process_txt_bulk_upload(self.github_uploader, file_entries)
            logger.info(f"=== BULK UPLOAD COMPLETED: {len(results)} results ===")
            
            # Count results
            successful_results = [(name, orig, github) for name, orig, github in results if github]
            failed_count = len(results) - len(successful_results)
            
            logger.info(f"=== UPLOAD SUMMARY ===: {len(successful_results)} successful, {failed_count} failed")
            
            if not successful_results:
                return (
                    "❌ **All file uploads failed!**\n\n"
                    "**Possible reasons:**\n"
                    "• URLs are not accessible\n"
                    "• Files are too large (100MB limit)\n"
                    "• URLs are not direct download links\n"
                    "• Network connectivity issues\n\n"
                    "Please check your URLs and try again."
                )
            
            # Create result txt file with Unicode support
            logger.info("=== CREATING RESULT FILE ===")
            result_file_path = create_txt_result_file(successful_results, "github_links.txt")
            
            # Upload result file to GitHub
            logger.info("=== UPLOADING RESULT FILE ===")
            result_github_url = self.github_uploader.upload_file(result_file_path, "github_links.txt")
            
            # Import here to avoid circular imports
            from bot_integration import get_upload_response_with_proxy
            result_response = get_upload_response_with_proxy(result_github_url, "github_links.txt")
            
            # Format final message
            summary_msg = format_txt_result_message(
                len(file_entries), 
                len(successful_results), 
                failed_count, 
                result_github_url
            )
            
            logger.info("=== TXT UPLOAD PROCESSING COMPLETED SUCCESSFULLY ===")
            return f"{summary_msg}\n\n{result_response}"
            
        except Exception as e:
            logger.error(f"=== ERROR IN TXT UPLOAD PROCESSING ===: {e}", exc_info=True)
            return (
                f"❌ **Error processing txt upload:** {str(e)}\n\n"
                f"**Please check:**\n"
                f"• Your message format is correct\n"
                f"• URLs are accessible\n"
                f"• Files are not too large\n\n"
                f"Use `/txt_help` for detailed instructions."
            )
    
    def get_txt_upload_help(self) -> str:
        """Get help message for txt upload format"""
        return get_txt_upload_help()

# MAIN FUNCTIONS FOR BOT.PY TO USE:

async def handle_txt_upload_message(github_uploader: GitHubUploader, message_text: str) -> Optional[str]:
    """
    MAIN FUNCTION: Handle txt upload message - returns response if it's a txt upload, None otherwise
    bot.py should call this function for every message BEFORE normal processing
    """
    try:
        logger.info("=== HANDLE_TXT_UPLOAD_MESSAGE CALLED ===")
        integration = TxtBotIntegration(github_uploader)
        
        if integration.should_process_as_txt_upload(message_text):
            logger.info("=== PROCESSING AS TXT UPLOAD ===")
            return await integration.process_txt_upload_message(message_text)
        
        logger.info("=== NOT A TXT UPLOAD REQUEST ===")
        return None
    except Exception as e:
        logger.error(f"=== ERROR IN HANDLE_TXT_UPLOAD_MESSAGE ===: {e}", exc_info=True)
        return f"❌ Error handling txt upload: {str(e)}"

def is_txt_upload_message(message_text: str) -> bool:
    """
    MAIN FUNCTION: Check if message is a txt upload request (requires command)
    bot.py should call this to check before normal processing
    """
    result = is_txt_upload_request(message_text)
    logger.info(f"=== IS_TXT_UPLOAD_MESSAGE ===: {result}")
    return result

def get_txt_help() -> str:
    """
    MAIN FUNCTION: Get txt upload help message
    bot.py should call this for help commands
    """
    return get_txt_upload_help()
