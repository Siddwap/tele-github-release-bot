
import asyncio
import logging
import os
import tempfile
from typing import List, Tuple, Optional
from urllib.parse import urlparse
import aiohttp
from github_uploader import GitHubUploader
from config import BotConfig

logger = logging.getLogger(__name__)

class TxtFileHandler:
    def __init__(self, config: BotConfig):
        self.config = config
        self.github_uploader = GitHubUploader(
            token=config.github_token,
            repo=config.github_repo,
            release_tag=config.github_release_tag
        )
    
    def parse_txt_content(self, content: str) -> List[Tuple[str, str]]:
        """Parse txt file content to extract filename:url pairs"""
        lines = content.strip().split('\n')
        file_pairs = []
        
        for line in lines:
            line = line.strip()
            if ':' in line and line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    filename = parts[0].strip()
                    url = parts[1].strip()
                    if filename and url:
                        file_pairs.append((filename, url))
        
        return file_pairs
    
    def get_file_extension(self, url: str, filename: str = "") -> str:
        """Get file extension from URL or filename"""
        if filename and '.' in filename:
            return filename.split('.')[-1].lower()
        
        parsed_url = urlparse(url)
        path = parsed_url.path
        if '.' in path:
            return path.split('.')[-1].lower().split('?')[0]
        
        return 'unknown'
    
    def is_m3u8_file(self, url: str, filename: str = "") -> bool:
        """Check if file is M3U8 based on URL or filename"""
        extension = self.get_file_extension(url, filename)
        return extension in ['m3u8', 'm3u']
    
    async def download_regular_file(self, url: str, filename: str, progress_callback=None) -> bytes:
        """Download regular file (non-M3U8)"""
        logger.info(f"Downloading regular file: {filename} from {url}")
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download {filename}: HTTP {response.status}")
                
                content_length = response.headers.get('Content-Length')
                if content_length:
                    content_length = int(content_length)
                
                downloaded = 0
                chunks = []
                
                async for chunk in response.content.iter_chunked(8192):
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    
                    if progress_callback and content_length:
                        progress = (downloaded / content_length) * 100
                        await progress_callback(int(progress))
                
                return b''.join(chunks)
    
    async def download_m3u8_file(self, url: str, filename: str, progress_callback=None) -> bytes:
        """Download M3U8 file using existing M3U8 downloader logic"""
        from m3u8_downloader import M3U8Downloader
        
        logger.info(f"Downloading M3U8 file: {filename} from {url}")
        
        downloader = M3U8Downloader()
        
        # Create temporary file for M3U8 download
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
            temp_path = temp_file.name
        
        try:
            await downloader.download_m3u8(url, temp_path, progress_callback)
            
            # Read the downloaded file
            with open(temp_path, 'rb') as f:
                return f.read()
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    
    async def process_txt_upload(self, txt_content: str, return_links: bool = False, progress_callback=None) -> str:
        """Process txt file upload and optionally return GitHub links"""
        file_pairs = self.parse_txt_content(txt_content)
        
        if not file_pairs:
            return "❌ No valid filename:url pairs found in txt file"
        
        logger.info(f"Processing {len(file_pairs)} files from txt upload")
        
        uploaded_links = []
        failed_files = []
        
        for i, (filename, url) in enumerate(file_pairs):
            try:
                logger.info(f"Processing file {i+1}/{len(file_pairs)}: {filename}")
                
                # Create progress callback for this specific file
                async def file_progress(percent):
                    if progress_callback:
                        overall_progress = ((i / len(file_pairs)) * 100) + (percent / len(file_pairs))
                        await progress_callback(f"Uploading {filename}: {percent}%", int(overall_progress))
                
                # Determine file type and download accordingly
                if self.is_m3u8_file(url, filename):
                    file_data = await self.download_m3u8_file(url, filename, file_progress)
                    # Ensure M3U8 files have .mp4 extension
                    if not filename.lower().endswith('.mp4'):
                        filename = f"{filename}.mp4"
                else:
                    file_data = await self.download_regular_file(url, filename, file_progress)
                
                # Upload to GitHub
                github_url = await self.github_uploader.upload_asset(file_data, filename)
                uploaded_links.append((filename, github_url))
                
                logger.info(f"Successfully uploaded {filename}")
                
            except Exception as e:
                logger.error(f"Failed to process {filename}: {e}")
                failed_files.append((filename, str(e)))
        
        # Generate response
        if return_links and uploaded_links:
            # Create txt content with GitHub links
            link_content = "\n".join([f"{name} : {url}" for name, url in uploaded_links])
            
            response = f"✅ Successfully uploaded {len(uploaded_links)} files!\n\n"
            response += "📋 GitHub Links:\n```\n"
            response += link_content
            response += "\n```"
            
            if failed_files:
                response += f"\n\n❌ Failed files ({len(failed_files)}):\n"
                for name, error in failed_files:
                    response += f"• {name}: {error}\n"
        else:
            response = f"✅ Successfully uploaded {len(uploaded_links)} files!"
            
            if failed_files:
                response += f"\n❌ Failed files ({len(failed_files)}):\n"
                for name, error in failed_files:
                    response += f"• {name}: {error}\n"
        
        return response
