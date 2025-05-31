
import aiohttp
import asyncio
import logging
import os
import tempfile
import re
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

class M3U8Handler:
    def __init__(self):
        self.session_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
    
    async def is_m3u8_url(self, url: str) -> bool:
        """Check if URL is an M3U8 playlist"""
        try:
            # Check file extension
            if url.lower().endswith('.m3u8'):
                return True
            
            # Check content type
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout, headers=self.session_headers) as session:
                async with session.head(url) as response:
                    content_type = response.headers.get('content-type', '').lower()
                    return 'mpegurl' in content_type or 'vnd.apple.mpegurl' in content_type
        except:
            return False
    
    async def download_m3u8_content(self, url: str) -> str:
        """Download M3U8 playlist content"""
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout, headers=self.session_headers) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download M3U8: HTTP {response.status}")
                return await response.text()
    
    def parse_m3u8_qualities(self, content: str, base_url: str) -> List[Dict]:
        """Parse M3U8 master playlist to extract quality options"""
        qualities = []
        lines = content.strip().split('\n')
        
        for i, line in enumerate(lines):
            if line.startswith('#EXT-X-STREAM-INF:'):
                # Extract resolution and bandwidth
                resolution_match = re.search(r'RESOLUTION=(\d+x\d+)', line)
                bandwidth_match = re.search(r'BANDWIDTH=(\d+)', line)
                
                resolution = resolution_match.group(1) if resolution_match else "Unknown"
                bandwidth = int(bandwidth_match.group(1)) if bandwidth_match else 0
                
                # Get the playlist URL (next line)
                if i + 1 < len(lines):
                    playlist_url = lines[i + 1].strip()
                    if not playlist_url.startswith('http'):
                        playlist_url = urljoin(base_url, playlist_url)
                    
                    # Extract quality from resolution
                    if 'x' in resolution:
                        height = int(resolution.split('x')[1])
                        quality_name = f"{height}p"
                    else:
                        quality_name = f"Quality {len(qualities) + 1}"
                    
                    qualities.append({
                        'name': quality_name,
                        'resolution': resolution,
                        'bandwidth': bandwidth,
                        'url': playlist_url
                    })
        
        # Sort by quality (highest first)
        qualities.sort(key=lambda x: x['bandwidth'], reverse=True)
        return qualities
    
    def parse_m3u8_segments(self, content: str, base_url: str) -> List[str]:
        """Parse M3U8 playlist to extract video segment URLs"""
        segments = []
        lines = content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                if not line.startswith('http'):
                    segment_url = urljoin(base_url, line)
                else:
                    segment_url = line
                segments.append(segment_url)
        
        return segments
    
    async def download_video_segments(self, segments: List[str], output_file: str, progress_callback=None) -> int:
        """Download all video segments and combine them into a single file"""
        total_segments = len(segments)
        total_downloaded = 0
        
        timeout = aiohttp.ClientTimeout(total=None, connect=30)
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=10,
            ttl_dns_cache=300,
            use_dns_cache=True
        )
        
        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers=self.session_headers
        ) as session:
            
            with open(output_file, 'wb') as f:
                for i, segment_url in enumerate(segments):
                    try:
                        async with session.get(segment_url) as response:
                            if response.status == 200:
                                chunk_size = 1024 * 1024  # 1MB chunks
                                async for chunk in response.content.iter_chunked(chunk_size):
                                    f.write(chunk)
                                    total_downloaded += len(chunk)
                                
                                # Update progress
                                if progress_callback:
                                    progress = ((i + 1) / total_segments) * 100
                                    await progress_callback(progress, i + 1, total_segments, total_downloaded)
                            else:
                                logger.warning(f"Failed to download segment {i + 1}: HTTP {response.status}")
                    
                    except Exception as e:
                        logger.error(f"Error downloading segment {i + 1}: {e}")
                        # Continue with next segment instead of failing completely
                        continue
        
        return total_downloaded
    
    async def process_m3u8_url(self, url: str, selected_quality: Optional[str] = None) -> Tuple[str, List[Dict], Optional[str]]:
        """
        Process M3U8 URL and return qualities or download path
        Returns: (temp_file_path, qualities, selected_playlist_url)
        """
        try:
            # Download master playlist
            master_content = await self.download_m3u8_content(url)
            base_url = '/'.join(url.split('/')[:-1]) + '/'
            
            # Check if it's a master playlist (contains quality options)
            if '#EXT-X-STREAM-INF:' in master_content:
                qualities = self.parse_m3u8_qualities(master_content, base_url)
                
                if not qualities:
                    raise Exception("No video qualities found in M3U8 playlist")
                
                # If no quality selected, return available qualities
                if selected_quality is None:
                    return None, qualities, None
                
                # Find selected quality
                selected_playlist = None
                for quality in qualities:
                    if quality['name'].lower() == selected_quality.lower():
                        selected_playlist = quality['url']
                        break
                
                if not selected_playlist:
                    # Default to highest quality
                    selected_playlist = qualities[0]['url']
                
                # Download the selected quality playlist
                playlist_content = await self.download_m3u8_content(selected_playlist)
                playlist_base_url = '/'.join(selected_playlist.split('/')[:-1]) + '/'
            else:
                # Direct playlist (no quality options)
                playlist_content = master_content
                playlist_base_url = base_url
                selected_playlist = url
            
            # Parse segments from the playlist
            segments = self.parse_m3u8_segments(playlist_content, playlist_base_url)
            
            if not segments:
                raise Exception("No video segments found in M3U8 playlist")
            
            # Create temporary file for the video
            temp_fd, temp_path = tempfile.mkstemp(suffix='.mp4')
            os.close(temp_fd)  # Close the file descriptor, we'll open it later
            
            return temp_path, [], selected_playlist
            
        except Exception as e:
            logger.error(f"Error processing M3U8 URL: {e}")
            raise
    
    async def download_m3u8_video(self, url: str, output_file: str, selected_quality: Optional[str] = None, progress_callback=None) -> int:
        """Download complete M3U8 video to output file"""
        try:
            # Process M3U8 URL
            temp_path, qualities, selected_playlist = await self.process_m3u8_url(url, selected_quality)
            
            if qualities:
                # This means we need quality selection
                raise Exception("Quality selection required")
            
            # Download playlist content for segments
            playlist_content = await self.download_m3u8_content(selected_playlist or url)
            playlist_base_url = '/'.join((selected_playlist or url).split('/')[:-1]) + '/'
            
            # Parse segments
            segments = self.parse_m3u8_segments(playlist_content, playlist_base_url)
            
            # Download all segments
            total_size = await self.download_video_segments(segments, output_file, progress_callback)
            
            return total_size
            
        except Exception as e:
            logger.error(f"Error downloading M3U8 video: {e}")
            raise
