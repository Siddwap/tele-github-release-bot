
import aiohttp
import logging
from typing import Callable, Optional, List, Dict
import json
import io
import os
import time

logger = logging.getLogger(__name__)

class GitHubUploader:
    def __init__(self, token: str, repo: str, release_tag: str):
        self.token = token
        self.repo = repo
        self.release_tag = release_tag
        self.api_url = "https://api.github.com"
        self.upload_url = "https://uploads.github.com"
        
    async def get_release_info(self) -> dict:
        """Get release information by tag"""
        url = f"{self.api_url}/repos/{self.repo}/releases/tags/{self.release_tag}"
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 404:
                    raise Exception(f"Release with tag '{self.release_tag}' not found")
                elif response.status != 200:
                    raise Exception(f"Failed to get release info: HTTP {response.status}")
                
                return await response.json()

    async def delete_existing_asset(self, release_id: int, filename: str) -> bool:
        """Delete existing asset if it exists"""
        url = f"{self.api_url}/repos/{self.repo}/releases/{release_id}/assets"
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return False
                
                assets = await response.json()
                for asset in assets:
                    if asset['name'] == filename:
                        # Delete the asset
                        delete_url = f"{self.api_url}/repos/{self.repo}/releases/assets/{asset['id']}"
                        async with session.delete(delete_url, headers=headers) as delete_response:
                            logger.info(f"Deleted existing asset: {filename}")
                            return delete_response.status == 204
                
                return False

    async def upload_asset_streaming(self, file_path: str, filename: str, file_size: int, progress_callback: Optional[Callable] = None) -> str:
        """Upload file as release asset using streaming from file with speed tracking"""
        try:
            # Get release info
            release_info = await self.get_release_info()
            release_id = release_info['id']
            upload_url_template = release_info['upload_url']
            
            # Remove existing asset if it exists
            await self.delete_existing_asset(release_id, filename)
            
            # Prepare upload URL
            upload_url = upload_url_template.replace('{?name,label}', f'?name={filename}')
            
            headers = {
                "Authorization": f"token {self.token}",
                "Content-Type": "application/octet-stream",
                "Content-Length": str(file_size)
            }
            
            # Create async generator for streaming upload with speed tracking
            async def file_generator():
                chunk_size = 1024 * 1024  # 1MB chunks
                uploaded = 0
                start_time = time.time()
                last_callback_time = start_time
                last_callback_bytes = 0
                
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        
                        uploaded += len(chunk)
                        current_time = time.time()
                        
                        # Call progress callback with proper speed calculation
                        if progress_callback and (current_time - last_callback_time >= 0.5 or uploaded == file_size):
                            await progress_callback(uploaded)
                            last_callback_time = current_time
                            last_callback_bytes = uploaded
                        
                        yield chunk

            # Upload with streaming
            async with aiohttp.ClientSession() as session:
                async with session.post(upload_url, headers=headers, data=file_generator()) as response:
                    if response.status not in [200, 201]:
                        error_text = await response.text()
                        raise Exception(f"Failed to upload asset: HTTP {response.status} - {error_text}")
                    
                    result = await response.json()
                    download_url = result['browser_download_url']
                    logger.info(f"Successfully uploaded {filename} to GitHub")
                    return download_url
                    
        except Exception as e:
            logger.error(f"Error uploading to GitHub: {e}")
            raise

    # Keep the old method for backward compatibility
    async def upload_asset(self, file_data: bytes, filename: str, progress_callback: Optional[Callable] = None) -> str:
        """Upload file as release asset (legacy method)"""
        # Use streaming method with temporary file
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(file_data)
            temp_file.flush()
            try:
                return await self.upload_asset_streaming(temp_file.name, filename, len(file_data), progress_callback)
            finally:
                os.unlink(temp_file.name)

    async def list_release_assets(self) -> List[Dict]:
        """List all assets in the release with proper pagination"""
        try:
            release_info = await self.get_release_info()
            release_id = release_info['id']
            
            all_assets = []
            page = 1
            per_page = 100  # Maximum allowed by GitHub API
            
            while True:
                url = f"{self.api_url}/repos/{self.repo}/releases/{release_id}/assets"
                headers = {
                    "Authorization": f"token {self.token}",
                    "Accept": "application/vnd.github.v3+json"
                }
                params = {
                    "page": page,
                    "per_page": per_page
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, params=params) as response:
                        if response.status != 200:
                            raise Exception(f"Failed to list assets: HTTP {response.status}")
                        
                        assets = await response.json()
                        
                        # If no assets returned, we've reached the end
                        if not assets:
                            break
                        
                        all_assets.extend(assets)
                        
                        # If we got fewer assets than requested, we've reached the end
                        if len(assets) < per_page:
                            break
                        
                        page += 1
            
            return all_assets
                    
        except Exception as e:
            logger.error(f"Error listing assets: {e}")
            raise

    async def delete_asset_by_name(self, filename: str) -> bool:
        """Delete an asset by filename"""
        try:
            assets = await self.list_release_assets()
            
            # Find the asset with matching filename
            target_asset = None
            for asset in assets:
                if asset['name'] == filename:
                    target_asset = asset
                    break
            
            if not target_asset:
                return False
            
            # Delete the asset
            url = f"{self.api_url}/repos/{self.repo}/releases/assets/{target_asset['id']}"
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers) as response:
                    if response.status == 204:
                        logger.info(f"Successfully deleted asset: {filename}")
                        return True
                    else:
                        logger.error(f"Failed to delete asset: HTTP {response.status}")
                        return False
                        
        except Exception as e:
            logger.error(f"Error deleting asset: {e}")
            raise

    async def rename_asset(self, old_filename: str, new_filename: str) -> bool:
        """Rename an asset by downloading and re-uploading with new name"""
        try:
            assets = await self.list_release_assets()
            
            # Find the asset with matching filename
            target_asset = None
            for asset in assets:
                if asset['name'] == old_filename:
                    target_asset = asset
                    break
            
            if not target_asset:
                return False
            
            # Download the asset content
            download_url = target_asset['browser_download_url']
            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/octet-stream"
            }
            
            async with aiohttp.ClientSession() as session:
                # Download the file content
                async with session.get(download_url) as download_response:
                    if download_response.status != 200:
                        raise Exception(f"Failed to download asset: HTTP {download_response.status}")
                    
                    file_content = await download_response.read()
                
                # Upload with new name
                await self.upload_asset(file_content, new_filename)
                
                # Delete the old asset
                await self.delete_asset_by_name(old_filename)
                
                logger.info(f"Successfully renamed asset: '{old_filename}' -> '{new_filename}'")
                return True
                        
        except Exception as e:
            logger.error(f"Error renaming asset: {e}")
            raise
