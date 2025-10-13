"""
Upload handlers for GitHub uploads
"""
import logging
import time

logger = logging.getLogger(__name__)


async def upload_to_github_streaming(github_uploader, temp_file_path: str, filename: str, file_size: int, 
                                     progress_msg, format_size_func, upload_queues: dict, should_stop: bool,
                                     current_item: int = 1, total_items: int = 1) -> str:
    """Upload file to GitHub with progress and speed using streaming"""
    uploaded = 0
    start_time = time.time()
    last_update_time = start_time
    last_uploaded = 0
    
    async def progress_callback(current: int):
        nonlocal uploaded, last_update_time, last_uploaded
        
        if should_stop:
            raise Exception("Upload stopped by admin command")
        
        uploaded = current
        current_time = time.time()
        progress = (current / file_size) * 100
        
        time_diff = current_time - last_update_time
        bytes_diff = current - last_uploaded
        speed = bytes_diff / time_diff if time_diff > 0 else 0
        
        if progress - getattr(progress_callback, 'last_progress', 0) >= 2 or time_diff >= 2:
            user_id = getattr(progress_msg, 'sender_id', 0)
            remaining = len(upload_queues.get(user_id, []))
            await progress_msg.edit(
                f"📤 **Uploading to GitHub...** ({current_item}/{total_items})\n\n"
                f"📁 {filename}\n"
                f"📊 {format_size_func(current)} / {format_size_func(file_size)}\n"
                f"⏳ {progress:.1f}%\n"
                f"🚀 Speed: {format_size_func(speed)}/s\n"
                f"📋 Remaining: {remaining} files\n"
                f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
            )
            progress_callback.last_progress = progress
            last_update_time = current_time
            last_uploaded = current
    
    return await github_uploader.upload_asset_streaming(temp_file_path, filename, file_size, progress_callback)


async def upload_to_github_streaming_with_progress(github_uploader, temp_file_path: str, filename: str, 
                                                   file_size: int, progress_msg, format_size_func, should_stop: bool,
                                                   current_item: int, total_items: int) -> str:
    """Upload file to GitHub with individual progress tracking for batch uploads"""
    uploaded = 0
    start_time = time.time()
    last_update_time = start_time
    last_uploaded = 0
    
    async def progress_callback(current: int):
        nonlocal uploaded, last_update_time, last_uploaded
        
        if should_stop:
            raise Exception("Upload stopped by admin command")
        
        uploaded = current
        current_time = time.time()
        progress = (current / file_size) * 100
        
        time_diff = current_time - last_update_time
        bytes_diff = current - last_uploaded
        speed = bytes_diff / time_diff if time_diff > 0 else 0
        
        if progress - getattr(progress_callback, f'last_progress_{current_item}', 0) >= 2 or time_diff >= 2:
            remaining = total_items - current_item
            await progress_msg.edit(
                f"📤 **Uploading to GitHub...** ({current_item}/{total_items})\n\n"
                f"📁 **Current:** `{filename}`\n"
                f"📊 **Size:** {format_size_func(current)} / {format_size_func(file_size)}\n"
                f"⏳ **Progress:** {progress:.1f}%\n"
                f"🚀 **Speed:** {format_size_func(speed)}/s\n"
                f"📋 **Remaining:** {remaining} files\n"
                f"{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}"
            )
            setattr(progress_callback, f'last_progress_{current_item}', progress)
            last_update_time = current_time
            last_uploaded = current
    
    return await github_uploader.upload_asset_streaming(temp_file_path, filename, file_size, progress_callback)


async def upload_to_github_streaming_silent(github_uploader, temp_file_path: str, filename: str, file_size: int) -> str:
    """Upload file to GitHub silently (no progress updates)"""
    return await github_uploader.upload_asset_streaming(temp_file_path, filename, file_size, None)
