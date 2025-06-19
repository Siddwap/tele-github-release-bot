
import logging
import asyncio
import aiohttp
from typing import List, Tuple, Dict, Optional
import os
from github_uploader import GitHubUploader

logger = logging.getLogger(__name__)

class BulkUploader:
    def __init__(self, github_uploader: GitHubUploader):
        self.github_uploader = github_uploader
        self.max_concurrent_downloads = 3
        self.max_file_size = 100 * 1024 * 1024  # 100MB limit
    
    async def download_file(self, session: aiohttp.ClientSession, url: str, filename: str) -> Optional[bytes]:
        """Download a single file from URL"""
        try:
            logger.info(f"Downloading {filename} from {url}")
            
            # Set headers to handle various file types
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.error(f"Failed to download {filename}: HTTP {response.status}")
                    return None
                
                # Check file size
                content_length = response.headers.get('content-length')
                if content_length and int(content_length) > self.max_file_size:
                    logger.error(f"File {filename} too large: {content_length} bytes")
                    return None
                
                content = await response.read()
                logger.info(f"Successfully downloaded {filename}: {len(content)} bytes")
                return content
                
        except Exception as e:
            logger.error(f"Error downloading {filename}: {e}")
            return None
    
    def upload_to_github(self, filename: str, content: bytes) -> Optional[str]:
        """Upload content to GitHub and return URL"""
        try:
            # Create temporary file with proper encoding for Unicode filenames
            import tempfile
            
            # Create a safe temporary filename but preserve original for GitHub upload
            temp_filename = f"temp_{hash(filename)}_{filename}"
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{temp_filename}") as temp_file:
                temp_file.write(content)
                temp_file_path = temp_file.name
            
            try:
                # Upload to GitHub with original Unicode filename
                github_url = self.github_uploader.upload_file(temp_file_path, filename)
                logger.info(f"Successfully uploaded {filename} to GitHub: {github_url}")
                return github_url
            finally:
                # Clean up temporary file
                try:
                    os.unlink(temp_file_path)
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Error uploading {filename} to GitHub: {e}")
            return None
    
    async def process_bulk_upload(self, file_entries: List[Tuple[str, str]]) -> List[Tuple[str, str, str]]:
        """Process bulk upload of files from URLs"""
        results = []
        
        # Create aiohttp session with proper timeout and encoding
        timeout = aiohttp.ClientTimeout(total=300)  # 5 minute timeout
        connector = aiohttp.TCPConnector(limit=10)
        
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            # Process files in batches to avoid overwhelming the system
            semaphore = asyncio.Semaphore(self.max_concurrent_downloads)
            
            async def process_single_file(file_name: str, file_url: str) -> Tuple[str, str, str]:
                async with semaphore:
                    try:
                        logger.info(f"Processing file: {file_name}")
                        
                        # Download file
                        content = await self.download_file(session, file_url, file_name)
                        
                        if content is None:
                            logger.error(f"Failed to download {file_name}")
                            return (file_name, file_url, "")
                        
                        # Upload to GitHub (run in thread pool to avoid blocking)
                        loop = asyncio.get_event_loop()
                        github_url = await loop.run_in_executor(
                            None, self.upload_to_github, file_name, content
                        )
                        
                        if github_url:
                            logger.info(f"Successfully processed {file_name}")
                            return (file_name, file_url, github_url)
                        else:
                            logger.error(f"Failed to upload {file_name} to GitHub")
                            return (file_name, file_url, "")
                            
                    except Exception as e:
                        logger.error(f"Error processing {file_name}: {e}")
                        return (file_name, file_url, "")
            
            # Process all files concurrently
            tasks = [process_single_file(name, url) for name, url in file_entries]
            results = await asyncio.gather(*tasks, return_exceptions=False)
        
        # Filter and log results
        successful = [r for r in results if r[2]]  # Has GitHub URL
        failed = [r for r in results if not r[2]]  # No GitHub URL
        
        logger.info(f"Bulk upload completed: {len(successful)} successful, {len(failed)} failed")
        
        return results

# Function for easy import
async def process_txt_bulk_upload(github_uploader: GitHubUploader, file_entries: List[Tuple[str, str]]) -> List[Tuple[str, str, str]]:
    """Process bulk upload from txt file entries"""
    uploader = BulkUploader(github_uploader)
    return await uploader.process_bulk_upload(file_entries)
