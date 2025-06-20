
import asyncio
import logging
import os
import tempfile
import aiohttp
import subprocess
from pathlib import Path
from typing import Optional
import aiofiles

from config import BotConfig

logger = logging.getLogger(__name__)

class GitHubUploader:
    def __init__(self, config: BotConfig):
        self.config = config
        self.github_token = config.github_token
        self.repo = config.github_repo
        self.release_tag = config.github_release_tag
        
        # GitHub API headers
        self.headers = {
            'Authorization': f'token {self.github_token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'TelegramBot-GitHubUploader'
        }
    
    async def upload_file(self, file_path: str, filename: str) -> Optional[str]:
        """Upload a file to GitHub release"""
        try:
            logger.info(f"Starting upload: {filename}")
            
            # Get release info
            release_url = f"https://api.github.com/repos/{self.repo}/releases/tags/{self.release_tag}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(release_url, headers=self.headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to get release info: {response.status}")
                        return None
                    
                    release_data = await response.json()
                    upload_url = release_data['upload_url'].replace('{?name,label}', '')
                
                # Upload file
                upload_url_with_params = f"{upload_url}?name={filename}"
                
                async with aiofiles.open(file_path, 'rb') as file:
                    file_data = await file.read()
                
                upload_headers = self.headers.copy()
                upload_headers['Content-Type'] = 'application/octet-stream'
                
                async with session.post(
                    upload_url_with_params,
                    data=file_data,
                    headers=upload_headers
                ) as response:
                    if response.status in [200, 201]:
                        result = await response.json()
                        download_url = result['browser_download_url']
                        logger.info(f"Successfully uploaded: {filename}")
                        return download_url
                    else:
                        error_text = await response.text()
                        logger.error(f"Upload failed: {response.status} - {error_text}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error uploading file {filename}: {e}")
            return None
    
    async def upload_file_from_url(self, url: str, filename: str) -> Optional[str]:
        """Download file from URL and upload to GitHub"""
        temp_file_path = None
        try:
            logger.info(f"Downloading file from URL: {url}")
            
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file_path = temp_file.name
            
            # Download file
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.error(f"Failed to download file: {response.status}")
                        return None
                    
                    # Write to temp file
                    async with aiofiles.open(temp_file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(8192):
                            await f.write(chunk)
            
            logger.info(f"File downloaded successfully, uploading to GitHub...")
            
            # Upload to GitHub
            github_url = await self.upload_file(temp_file_path, filename)
            
            return github_url
            
        except Exception as e:
            logger.error(f"Error downloading/uploading file from URL {url}: {e}")
            return None
        finally:
            # Clean up temp file
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
    
    async def upload_m3u8_from_url(self, m3u8_url: str, filename: str) -> Optional[str]:
        """Download M3U8 stream using yt-dlp and upload to GitHub"""
        temp_dir = None
        try:
            logger.info(f"Processing M3U8 stream: {m3u8_url}")
            
            # Create temporary directory
            temp_dir = tempfile.mkdtemp()
            
            # Ensure filename has proper extension
            if not filename.lower().endswith(('.mp4', '.mkv', '.avi')):
                filename += '.mp4'
            
            output_path = os.path.join(temp_dir, filename)
            
            # Use yt-dlp to download M3U8 stream
            cmd = [
                'yt-dlp',
                '--no-warnings',
                '--no-playlist',
                '--output', output_path,
                '--format', 'best[ext=mp4]/best',
                '--merge-output-format', 'mp4',
                m3u8_url
            ]
            
            logger.info("Starting yt-dlp download...")
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"yt-dlp failed: {stderr.decode()}")
                return None
            
            # Check if file was created
            if not os.path.exists(output_path):
                # yt-dlp might have created file with different name
                files = list(Path(temp_dir).glob('*'))
                if files:
                    output_path = str(files[0])
                    # Update filename to match actual downloaded file
                    filename = files[0].name
                else:
                    logger.error("No output file found after yt-dlp")
                    return None
            
            logger.info(f"M3U8 download completed: {filename}")
            
            # Upload to GitHub
            github_url = await self.upload_file(output_path, filename)
            
            return github_url
            
        except Exception as e:
            logger.error(f"Error processing M3U8 stream {m3u8_url}: {e}")
            return None
        finally:
            # Clean up temp directory
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
    
    async def delete_file_from_release(self, filename: str) -> bool:
        """Delete a file from GitHub release"""
        try:
            # Get release info and assets
            release_url = f"https://api.github.com/repos/{self.repo}/releases/tags/{self.release_tag}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(release_url, headers=self.headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to get release info: {response.status}")
                        return False
                    
                    release_data = await response.json()
                    assets = release_data.get('assets', [])
                
                # Find the asset to delete
                asset_id = None
                for asset in assets:
                    if asset['name'] == filename:
                        asset_id = asset['id']
                        break
                
                if not asset_id:
                    logger.warning(f"File {filename} not found in release")
                    return False
                
                # Delete the asset
                delete_url = f"https://api.github.com/repos/{self.repo}/releases/assets/{asset_id}"
                async with session.delete(delete_url, headers=self.headers) as response:
                    if response.status == 204:
                        logger.info(f"Successfully deleted: {filename}")
                        return True
                    else:
                        logger.error(f"Failed to delete file: {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error deleting file {filename}: {e}")
            return False
    
    async def list_release_files(self) -> list:
        """List all files in the GitHub release"""
        try:
            release_url = f"https://api.github.com/repos/{self.repo}/releases/tags/{self.release_tag}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(release_url, headers=self.headers) as response:
                    if response.status != 200:
                        logger.error(f"Failed to get release info: {response.status}")
                        return []
                    
                    release_data = await response.json()
                    assets = release_data.get('assets', [])
                    
                    files = []
                    for asset in assets:
                        files.append({
                            'name': asset['name'],
                            'size': asset['size'],
                            'download_url': asset['browser_download_url'],
                            'created_at': asset['created_at']
                        })
                    
                    return files
                    
        except Exception as e:
            logger.error(f"Error listing release files: {e}")
            return []
