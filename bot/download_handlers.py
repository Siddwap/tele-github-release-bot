"""
Download handlers for Telegram, URL, and YouTube downloads
"""
import asyncio
import logging
import time
import os
import tempfile
import aiohttp
import yt_dlp
from pytubefix import YouTube
from typing import Optional

logger = logging.getLogger(__name__)


async def download_telegram_file_streaming(client, document, temp_file, progress_msg, filename: str, 
                                          format_size_func, upload_queues: dict, should_stop: bool,
                                          current_item: int = 1, total_items: int = 1):
    """Download file from Telegram with progress and speed using streaming to temp file"""
    total_size = document.size
    downloaded = 0
    start_time = time.time()
    last_update_time = start_time
    last_downloaded = 0
    
    async def progress_callback(current, total):
        nonlocal downloaded, last_update_time, last_downloaded
        
        # Check if we should stop
        if should_stop:
            raise Exception("Upload stopped by admin command")
        
        downloaded = current
        current_time = time.time()
        progress = (current / total) * 100
        
        # Calculate speed
        time_diff = current_time - last_update_time
        bytes_diff = current - last_downloaded
        speed = bytes_diff / time_diff if time_diff > 0 else 0
        
        # Update every 2% progress or every 2 seconds
        if progress - getattr(progress_callback, 'last_progress', 0) >= 2 or time_diff >= 2:
            remaining = len(upload_queues.get(getattr(progress_msg, 'sender_id', 0), []))
            await progress_msg.edit(
                f"📥 **Downloading from Telegram...** ({current_item}/{total_items})\n\n"
                f"📁 {filename}\n"
                f"📊 {format_size_func(current)} / {format_size_func(total)}\n"
                f"⏳ {progress:.1f}%\n"
                f"🚀 Speed: {format_size_func(speed)}/s\n"
                f"📋 Remaining: {remaining} files\n"
                f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
            )
            progress_callback.last_progress = progress
            last_update_time = current_time
            last_downloaded = current
    
    # Download file to temporary file using streaming
    await client.download_media(
        document, 
        file=temp_file, 
        progress_callback=progress_callback
    )


async def download_from_url_streaming(url: str, temp_file, progress_msg, filename: str,
                                     format_size_func, upload_queues: dict, should_stop: bool,
                                     add_session_func, remove_session_func,
                                     current_item: int = 1, total_items: int = 1) -> int:
    """Download file from URL with progress and speed using streaming to temp file"""
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=30,
        ttl_dns_cache=300,
        use_dns_cache=True,
        enable_cleanup_closed=True
    )
    
    session = aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    )
    
    user_id = getattr(progress_msg, 'sender_id', 0)
    add_session_func(user_id, session)
    
    try:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to download: HTTP {response.status}")
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            last_update_time = start_time
            last_downloaded = 0
            
            chunk_size = 8 * 1024 * 1024  # 8MB chunks
            
            async for chunk in response.content.iter_chunked(chunk_size):
                if should_stop:
                    raise Exception("Upload stopped by admin command")
                
                temp_file.write(chunk)
                downloaded += len(chunk)
                current_time = time.time()
                
                if total_size > 0:
                    progress = (downloaded / total_size) * 100
                    
                    time_diff = current_time - last_update_time
                    bytes_diff = downloaded - last_downloaded
                    speed = bytes_diff / time_diff if time_diff > 0 else 0
                    
                    if progress - getattr(download_from_url_streaming, '_last_progress', 0) >= 2 or time_diff >= 2:
                        remaining = len(upload_queues.get(user_id, []))
                        await progress_msg.edit(
                            f"📥 **Downloading from URL...** ({current_item}/{total_items})\n\n"
                            f"📁 {filename}\n"
                            f"📊 {format_size_func(downloaded)} / {format_size_func(total_size)}\n"
                            f"⏳ {progress:.1f}%\n"
                            f"🚀 Speed: {format_size_func(speed)}/s\n"
                            f"📋 Remaining: {remaining} files\n"
                            f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
                        )
                        download_from_url_streaming._last_progress = progress
                        last_update_time = current_time
                        last_downloaded = downloaded
            
            temp_file.flush()
            return downloaded
    finally:
        remove_session_func(user_id, session)
        if not session.closed:
            await session.close()


async def download_from_url_streaming_with_progress(url: str, temp_file, progress_msg, filename: str,
                                                    format_size_func, should_stop: bool,
                                                    current_item: int, total_items: int) -> int:
    """Download file from URL with individual progress tracking for batch uploads"""
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=30,
        ttl_dns_cache=300,
        use_dns_cache=True,
        enable_cleanup_closed=True
    )
    
    session = aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    )
    
    try:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to download: HTTP {response.status}")
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            start_time = time.time()
            last_update_time = start_time
            last_downloaded = 0
            
            chunk_size = 8 * 1024 * 1024  # 8MB chunks
            
            async for chunk in response.content.iter_chunked(chunk_size):
                if should_stop:
                    raise Exception("Upload stopped by admin command")
                
                temp_file.write(chunk)
                downloaded += len(chunk)
                current_time = time.time()
                
                if total_size > 0:
                    progress = (downloaded / total_size) * 100
                    
                    time_diff = current_time - last_update_time
                    bytes_diff = downloaded - last_downloaded
                    speed = bytes_diff / time_diff if time_diff > 0 else 0
                    
                    if progress - getattr(download_from_url_streaming_with_progress, f'_last_batch_dl_progress_{current_item}', 0) >= 2 or time_diff >= 2:
                        remaining = total_items - current_item
                        await progress_msg.edit(
                            f"📥 **Downloading...** ({current_item}/{total_items})\n\n"
                            f"📁 **Current:** `{filename}`\n"
                            f"📊 **Size:** {format_size_func(downloaded)} / {format_size_func(total_size)}\n"
                            f"⏳ **Progress:** {progress:.1f}%\n"
                            f"🚀 **Speed:** {format_size_func(speed)}/s\n"
                            f"📋 **Remaining:** {remaining} files\n"
                            f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
                        )
                        setattr(download_from_url_streaming_with_progress, f'_last_batch_dl_progress_{current_item}', progress)
                        last_update_time = current_time
                        last_downloaded = downloaded
            
            temp_file.flush()
            return downloaded
    finally:
        if not session.closed:
            await session.close()


async def download_from_url_streaming_silent(url: str, temp_file, should_stop: bool) -> int:
    """Download file from URL silently (no progress updates)"""
    timeout = aiohttp.ClientTimeout(total=None, connect=30)
    connector = aiohttp.TCPConnector(
        limit=100,
        limit_per_host=30,
        ttl_dns_cache=300,
        use_dns_cache=True,
        enable_cleanup_closed=True
    )
    
    session = aiohttp.ClientSession(
        timeout=timeout,
        connector=connector,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
    )
    
    try:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to download: HTTP {response.status}")
            
            downloaded = 0
            chunk_size = 8 * 1024 * 1024  # 8MB chunks
            
            async for chunk in response.content.iter_chunked(chunk_size):
                if should_stop:
                    raise Exception("Upload stopped by admin command")
                
                temp_file.write(chunk)
                downloaded += len(chunk)
            
            temp_file.flush()
            return downloaded
    finally:
        if not session.closed:
            await session.close()


async def make_video_seekable(input_path: str, progress_msg=None) -> str:
    """Re-encode video to make it seekable with proper keyframes"""
    try:
        if progress_msg:
            await progress_msg.edit("🔄 **Optimizing video for seeking...**\n⏳ This may take a few minutes...")
        
        # Create output path
        dir_name = os.path.dirname(input_path)
        base_name = os.path.basename(input_path)
        output_path = os.path.join(dir_name, f"seekable_{base_name}")
        
        logger.info(f"Making video seekable: {input_path} -> {output_path}")
        
        # FFmpeg command to re-encode with keyframes every 2 seconds
        # Using faster preset to reduce processing time
        process = await asyncio.create_subprocess_exec(
            'ffmpeg',
            '-i', input_path,
            '-c:v', 'libx264',
            '-preset', 'fast',  # Faster than medium but still good quality
            '-crf', '23',
            '-c:a', 'copy',  # Copy audio without re-encoding to save time
            '-movflags', '+faststart',  # Enable faststart for web playback
            '-g', '48',  # GOP size (keyframe interval) - 2 seconds at 24fps
            '-keyint_min', '24',  # Minimum keyframe interval
            '-maxrate', '2M',
            '-bufsize', '4M',
            output_path,
            '-y',  # Overwrite output file
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            logger.info(f"Successfully made video seekable: {output_path}")
            # Remove original file and rename
            try:
                os.unlink(input_path)
                final_path = input_path  # Use original path name
                os.rename(output_path, final_path)
                logger.info(f"Renamed seekable video to: {final_path}")
                return final_path
            except Exception as rename_error:
                logger.error(f"Error renaming file: {rename_error}")
                return output_path
        else:
            logger.error(f"FFmpeg error: {stderr.decode()}")
            # If re-encoding fails, return original
            if progress_msg:
                await progress_msg.edit("⚠️ **Video optimization failed, using original...**")
            return input_path
            
    except Exception as e:
        logger.error(f"Error making video seekable: {e}")
        # Return original if processing fails
        if progress_msg:
            await progress_msg.edit("⚠️ **Video optimization failed, using original...**")
        return input_path


async def download_youtube_with_ytdlp(youtube_url: str, quality: int, filename: str, 
                                     progress_msg, format_size_func, cookies_file: str = "cookies.txt") -> Optional[str]:
    """Download YouTube video using yt-dlp with cookies for authentication and seekable videos"""
    output_path = None
    temp_dir = None
    
    try:
        await progress_msg.edit(
            f"📥 **Downloading video from YouTube...**\n"
            f"📁 **File:** `{filename}`\n"
            f"📊 **Quality:** {quality}p\n"
            f"⏳ Initializing yt-dlp..."
        )
        
        logger.info(f"Starting YouTube download with yt-dlp, quality: {quality}p")
        logger.info(f"URL: {youtube_url}")
        logger.info(f"Using cookies file: {cookies_file}")
        
        # Check if cookies file exists
        cookies_path = os.path.abspath(cookies_file)
        if not os.path.exists(cookies_path):
            logger.warning(f"Cookies file not found at {cookies_path}, proceeding without cookies")
            cookies_path = None
        
        temp_dir = tempfile.mkdtemp()
        output_template = os.path.join(temp_dir, "video.%(ext)s")
        
        # Enhanced yt-dlp options for seekable videos
        ydl_opts = {
            'outtmpl': output_template,
            # Priority format selection for seekable H.264 videos
            'format': f'bestvideo[height<={quality}][vcodec^=avc1]+bestaudio/best[height<={quality}]/best',
            'merge_output_format': 'mp4',
            'quiet': True,
            'no_warnings': False,
            'extractaudio': False,
            'keepvideo': False,
            'writethumbnail': False,
            'continuedl': True,
            'noprogress': True,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            'keep_fragments': True,
            # Post-processing for better compatibility
            'postprocessor_args': {
                'ffmpeg': [
                    '-c', 'copy',  # Try to copy streams without re-encoding first
                    '-movflags', '+faststart'  # Enable faststart for web playback
                ]
            },
        }
        
        # Add cookies if available
        if cookies_path:
            ydl_opts.update({
                'cookiefile': cookies_path,
                'cookiesfrombrowser': None,  # Disable auto browser detection
            })
        
        progress_data = {}
        
        def progress_hook(d):
            """Progress hook for yt-dlp"""
            if d['status'] == 'downloading':
                progress_data.update({
                    'status': 'downloading',
                    'filename': d.get('filename', ''),
                    'percent': d.get('_percent_str', '0%').strip(),
                    'speed': d.get('_speed_str', 'N/A'),
                    'total_size': d.get('_total_bytes_str', 'N/A'),
                    'eta': d.get('_eta_str', 'N/A')
                })
            elif d['status'] == 'finished':
                progress_data.update({
                    'status': 'finished',
                    'filename': d.get('filename', ''),
                    'final_path': d.get('filename', '')
                })
            elif d['status'] == 'error':
                progress_data.update({
                    'status': 'error',
                    'error': d.get('error', 'Unknown error')
                })
        
        ydl_opts['progress_hooks'] = [progress_hook]
        
        async def update_progress():
            """Async function to update progress messages"""
            while True:
                if progress_data.get('status') == 'downloading':
                    await progress_msg.edit(
                        f"📥 **Downloading from YouTube...**\n"
                        f"📁 **File:** `{filename}`\n"
                        f"📊 **Progress:** {progress_data.get('percent', '0%')}\n"
                        f"🚀 **Speed:** {progress_data.get('speed', 'N/A')}\n"
                        f"📊 **Size:** {progress_data.get('total_size', 'N/A')}\n"
                        f"⏱️ **ETA:** {progress_data.get('eta', 'N/A')}\n"
                        f"⏳ Downloading..."
                    )
                elif progress_data.get('status') == 'finished':
                    await progress_msg.edit(
                        f"✅ **Download complete!**\n"
                        f"📁 **File:** `{filename}`\n"
                        f"📊 **Finalizing...**\n"
                        f"⏳ Processing video..."
                    )
                    break
                elif progress_data.get('status') == 'error':
                    await progress_msg.edit(
                        f"❌ **Download error!**\n"
                        f"📁 **File:** `{filename}`\n"
                        f"💥 **Error:** {progress_data.get('error', 'Unknown error')}\n"
                        f"⏳ Retrying..."
                    )
                    break
                
                await asyncio.sleep(2)  # Update every 2 seconds
        
        # Start progress updates
        progress_task = asyncio.create_task(update_progress())
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info first
                await progress_msg.edit("🔍 **Fetching video info...**")
                info = ydl.extract_info(youtube_url, download=False)
                
                video_title = info.get('title', 'Unknown Title')
                duration = info.get('duration', 0)
                uploader = info.get('uploader', 'Unknown Uploader')
                
                # Log available formats for debugging
                formats = info.get('formats', [])
                h264_formats = [f for f in formats if f.get('vcodec', '').startswith('avc1')]
                logger.info(f"Available H.264 formats: {len(h264_formats)}")
                for fmt in h264_formats[:3]:  # Log first 3 H.264 formats
                    logger.info(f"H.264 format: {fmt.get('format_note', 'N/A')} - {fmt.get('vcodec', 'N/A')} - {fmt.get('resolution', 'N/A')}")
                
                await progress_msg.edit(
                    f"📥 **Downloading video from YouTube...**\n"
                    f"📁 **File:** `{filename}`\n"
                    f"🎬 **Title:** {video_title[:50]}...\n"
                    f"👤 **Uploader:** {uploader}\n"
                    f"⏱️ **Duration:** {duration} seconds\n"
                    f"📊 **Quality:** {quality}p\n"
                    f"⏳ Starting download..."
                )
                
                # Start the download
                ydl.download([youtube_url])
                
                # Wait for progress to finish
                await asyncio.sleep(1)
                progress_task.cancel()
                
        except Exception as e:
            progress_task.cancel()
            raise e
        
        # Find the downloaded file
        downloaded_files = []
        for file in os.listdir(temp_dir):
            if any(file.endswith(ext) for ext in ['.mp4', '.mkv', '.webm', '.flv', '.avi']):
                downloaded_files.append(os.path.join(temp_dir, file))
        
        if not downloaded_files:
            raise Exception("Download failed - no video file found in output directory")
        
        output_path = downloaded_files[0]
        
        # Verify file exists and has content
        if not os.path.exists(output_path):
            raise Exception("Download failed - output file not created")
        
        file_size = os.path.getsize(output_path)
        logger.info(f"Downloaded file size: {format_size_func(file_size)}")
        
        if file_size == 0:
            raise Exception("Downloaded file is empty (0 bytes)")
        
        await progress_msg.edit(
            f"✅ **Download complete!**\n"
            f"📁 **File:** `{filename}`\n"
            f"🎬 **Title:** {video_title[:50]}...\n"
            f"📊 **Size:** {format_size_func(file_size)}\n"
            f"📊 **Quality:** {quality}p\n"
            f"⏳ Optimizing video..."
        )
        
        return output_path
        
    except Exception as e:
        logger.error(f"Error downloading YouTube video with yt-dlp: {e}")
        # Clean up temp directory on error
        if temp_dir and os.path.exists(temp_dir):
            import shutil
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up temp directory: {cleanup_error}")
        raise e


async def download_youtube_with_pytubefix(youtube_url: str, quality: int, filename: str, 
                                         progress_msg, format_size_func) -> Optional[str]:
    """Download YouTube video using pytubefix - Fallback method"""
    output_path = None
    
    try:
        await progress_msg.edit(
            f"📥 **Downloading video from YouTube...**\n"
            f"📁 **File:** `{filename}`\n"
            f"📊 **Quality:** {quality}p\n"
            f"⏳ Initializing..."
        )
        
        logger.info(f"Starting YouTube download with quality: {quality}p")
        logger.info(f"URL: {youtube_url}")
        
        def on_progress(stream, chunk, bytes_remaining):
            """Progress callback for download"""
            try:
                total_size = stream.filesize
                bytes_downloaded = total_size - bytes_remaining
                percentage = (bytes_downloaded / total_size) * 100
                logger.info(f"Download progress: {percentage:.1f}%")
            except Exception as e:
                logger.error(f"Error in progress callback: {e}")
        
        # Try different clients without use_po_token
        clients_to_try = ['WEB', 'ANDROID', 'WEB_EMBEDDED', 'MWEB', 'ANDROID_EMBEDDED']
        yt = None
        
        for client in clients_to_try:
            try:
                logger.info(f"Trying client: {client}")
                yt = YouTube(youtube_url, client=client, on_progress_callback=on_progress)
                break
            except Exception as e:
                logger.warning(f"Client {client} failed: {e}")
                continue
        
        if yt is None:
            raise Exception("All YouTube clients failed. YouTube may be blocking requests.")
        
        logger.info(f"Video title: {yt.title}")
        logger.info(f"Video length: {yt.length} seconds")
        
        await progress_msg.edit(
            f"📥 **Downloading video from YouTube...**\n"
            f"📁 **File:** `{filename}`\n"
            f"🎬 **Title:** {yt.title[:50]}...\n"
            f"📊 **Quality:** {quality}p\n"
            f"⏳ Selecting best stream..."
        )
        
        # Rest of your existing pytubefix code...
        stream = None
        
        # Try to get progressive stream at exact quality
        stream = yt.streams.filter(progressive=True, file_extension='mp4', res=f'{quality}p').first()
        
        # If not available, try adaptive stream (video only) and merge later
        if not stream:
            logger.info(f"No progressive stream at {quality}p, trying adaptive...")
            stream = yt.streams.filter(adaptive=True, file_extension='mp4', res=f'{quality}p').first()
        
        # Fallback to highest quality progressive stream
        if not stream:
            logger.info(f"No stream at {quality}p, getting highest quality progressive...")
            stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
        
        # Last resort: get any mp4 stream
        if not stream:
            logger.info("Getting any available mp4 stream...")
            stream = yt.streams.filter(file_extension='mp4').first()
        
        if not stream:
            raise Exception("No suitable video stream found")
        
        logger.info(f"Selected stream: {stream.resolution} - {stream.mime_type} - Progressive: {stream.is_progressive}")
        
        await progress_msg.edit(
            f"📥 **Downloading video from YouTube...**\n"
            f"📁 **File:** `{filename}`\n"
            f"🎬 **Title:** {yt.title[:50]}...\n"
            f"📊 **Quality:** {stream.resolution}\n"
            f"⏳ Downloading..."
        )
        
        # Create temp directory for download
        temp_dir = tempfile.mkdtemp()
        
        # Download the stream
        output_path = stream.download(output_path=temp_dir, filename='video.mp4')
        
        logger.info(f"Downloaded to: {output_path}")
        
        # Verify file exists and has content
        if not os.path.exists(output_path):
            raise Exception("Download failed - output file not created")
        
        file_size = os.path.getsize(output_path)
        logger.info(f"Downloaded file size: {format_size_func(file_size)}")
        
        if file_size == 0:
            raise Exception("Downloaded file is empty (0 bytes)")
        
        await progress_msg.edit(
            f"✅ **Download complete!**\n"
            f"📁 **File:** `{filename}`\n"
            f"🎬 **Title:** {yt.title[:50]}...\n"
            f"📊 **Size:** {format_size_func(file_size)}\n"
            f"📊 **Quality:** {stream.resolution}\n"
            f"⏳ Optimizing video..."
        )
        
        return output_path
        
    except Exception as e:
        logger.error(f"Error downloading YouTube video with pytubefix: {e}")
        # Clean up temp file on error
        if output_path and os.path.exists(output_path):
            try:
                os.unlink(output_path)
            except:
                pass
        raise e


async def download_youtube_video(youtube_url: str, quality: int, filename: str, 
                                progress_msg, format_size_func, cookies_file: str = "cookies.txt",
                                make_seekable: bool = True) -> Optional[str]:
    """Main YouTube download function with seekable video support"""
    try:
        # First try with yt-dlp (with cookies)
        output_path = await download_youtube_with_ytdlp(youtube_url, quality, filename, progress_msg, format_size_func, cookies_file)
        
        # Make video seekable if requested
        if make_seekable and output_path:
            output_path = await make_video_seekable(output_path, progress_msg)
        
        return output_path
        
    except Exception as e:
        logger.warning(f"yt-dlp with cookies failed, trying without cookies: {e}")
        try:
            # Try yt-dlp without cookies
            output_path = await download_youtube_with_ytdlp(youtube_url, quality, filename, progress_msg, format_size_func, None)
            
            # Make video seekable if requested
            if make_seekable and output_path:
                output_path = await make_video_seekable(output_path, progress_msg)
            
            return output_path
            
        except Exception as e2:
            logger.warning(f"yt-dlp without cookies failed, trying pytubefix: {e2}")
            try:
                # Final fallback to pytubefix
                output_path = await download_youtube_with_pytubefix(youtube_url, quality, filename, progress_msg, format_size_func)
                
                # Make video seekable if requested
                if make_seekable and output_path:
                    output_path = await make_video_seekable(output_path, progress_msg)
                
                return output_path
                
            except Exception as e3:
                logger.error(f"All YouTube download methods failed: {e3}")
                raise Exception(f"YouTube download failed: {e3}")


async def fetch_youtube_video_data(youtube_url: str) -> Optional[dict]:
    """Fetch YouTube video data from API"""
    try:
        api_url = f"https://ytdl.testingsd9.workers.dev/?url={youtube_url}"
        
        timeout = aiohttp.ClientTimeout(total=60, connect=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(api_url) as response:
                if response.status != 200:
                    logger.error(f"API returned status {response.status}")
                    return None
                
                data = await response.json()
                return data
    except Exception as e:
        logger.error(f"Error fetching YouTube data: {e}")
        return None


async def merge_video_audio_ffmpeg(video_path: str, audio_path: str, output_path: str, progress_msg=None) -> bool:
    """Merge video and audio using FFmpeg"""
    try:
        if progress_msg:
            await progress_msg.edit("🔄 **Merging video and audio...**\n⏳ Please wait...")
        
        # Run FFmpeg to merge video and audio
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-i', video_path, '-i', audio_path,
            '-c:v', 'copy', '-c:a', 'aac', '-strict', 'experimental',
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            logger.info(f"Successfully merged video and audio to {output_path}")
            return True
        else:
            logger.error(f"FFmpeg error: {stderr.decode()}")
            return False
            
    except Exception as e:
        logger.error(f"Error merging video and audio: {e}")
        return False
