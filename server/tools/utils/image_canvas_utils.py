"""
Canvas-related utilities for image generation
Handles canvas operations, locking, and notifications
"""

import asyncio
import base64
import os
import random
import time
import json
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Dict, List, Any, Optional, Union, cast

import aiohttp
from nanoid import generate
from PIL import Image

from common import DEFAULT_PORT
from services.config_service import FILES_DIR
from services.db_service import db_service
from services.websocket_service import broadcast_session_update
from services.websocket_service import send_to_websocket
from utils.canvas import find_next_best_element_position

def generate_file_id() -> str:
    """Generate unique file ID"""
    return 'im_' + generate(size=8)


class CanvasLockManager:
    """Canvas lock manager to prevent concurrent operations causing position overlap"""

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def lock_canvas(self, canvas_id: str):
        if canvas_id not in self._locks:
            self._locks[canvas_id] = asyncio.Lock()

        async with self._locks[canvas_id]:
            yield


# Global lock manager instance
canvas_lock_manager = CanvasLockManager()



async def generate_new_image_element(
    canvas_id: str,
    fileid: str,
    image_data: Dict[str, Any],
    canvas_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate new image element for canvas"""
    if canvas_data is None:
        canvas = await db_service.get_canvas_data(canvas_id)
        if canvas is None:
            canvas = {"data": {}}
        canvas_data = canvas.get("data", {})



    new_x, new_y = await find_next_best_element_position(canvas_data)

    return {
        "type": "image",
        "id": fileid,
        "x": new_x,
        "y": new_y,
        "width": image_data.get("width", 0),
        "height": image_data.get("height", 0),
        "angle": 0,
        "fileId": fileid,
        "strokeColor": "#000000",
        "fillStyle": "solid",
        "strokeStyle": "solid",
        "boundElements": None,
        "roundness": None,
        "frameId": None,
        "backgroundColor": "transparent",
        "strokeWidth": 1,
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "seed": int(random.random() * 1000000),
        "version": 1,
        "versionNonce": int(random.random() * 1000000),
        "isDeleted": False,
        "index": None,
        "updated": 0,
        "link": None,
        "locked": False,
        "status": "saved",
        "scale": [1, 1],
        "crop": None,
    }


async def save_image_to_canvas(session_id: str, canvas_id: str, filename: str, mime_type: str, width: int, height: int) -> str:
    """Save image to canvas with proper locking and positioning"""
    # Use lock to ensure atomicity of the save process
    async with canvas_lock_manager.lock_canvas(canvas_id):
        # Fetch canvas data once inside the lock
        canvas: Optional[Dict[str, Any]] = await db_service.get_canvas_data(canvas_id)
        if canvas is None:
            canvas = {'data': {}}
        canvas_data: Dict[str, Any] = canvas.get('data', {})

        # Ensure 'elements' and 'files' keys exist
        if 'elements' not in canvas_data:
            canvas_data['elements'] = []
        if 'files' not in canvas_data:
            canvas_data['files'] = {}

        file_id = generate_file_id()
        url = f'/api/file/{filename}'

        file_data: Dict[str, Any] = {
            'mimeType': mime_type,
            'id': file_id,
            'dataURL': url,
            'created': int(time.time() * 1000),
        }

        new_image_element: Dict[str, Any] = await generate_new_image_element(
            canvas_id,
            file_id,
            {
                'width': width,
                'height': height,
            },
            canvas_data
        )

        # Update the canvas data with the new element and file info
        elements_list = cast(List[Dict[str, Any]], canvas_data['elements'])
        elements_list.append(new_image_element)
        canvas_data['files'][file_id] = file_data

        image_url = f"/api/file/{filename}"

        # Save the updated canvas data back to the database
        await db_service.save_canvas_data(canvas_id, json.dumps(canvas_data))

        # Broadcast image generation message to frontend
        await broadcast_session_update(session_id, canvas_id, {
            'type': 'image_generated',
            'element': new_image_element,
            'file': file_data,
            'image_url': image_url,
        })

        return image_url


async def send_image_start_notification(session_id: str, message: str) -> None:
    """Send image generation start notification"""
    await send_to_websocket(session_id, {
        'type': 'image_generation_start',
        'message': message
    })


async def send_image_error_notification(session_id: str, error_message: str) -> None:
    """Send image generation error notification"""
    await send_to_websocket(session_id, {
        'type': 'error',
        'error': error_message
    })


async def download_image_to_canvas_element(
    image_url: str,
    x: float = 0,
    y: float = 0,
    width: float = 0,
    height: float = 0
) -> Optional[Dict[str, Any]]:
    """
    Download an image from URL and save it locally for canvas use.
    
    Args:
        image_url: The URL of the image to download
        x: X position on canvas
        y: Y position on canvas
        width: Expected width (will use actual image width if 0)
        height: Expected height (will use actual image height if 0)
        
    Returns:
        Dict with file_id, url, width, height, and dataURL for canvas use
    """
    # Maximum file size: 20MB
    MAX_IMAGE_SIZE = 20 * 1024 * 1024
    
    try:
        # Handle data URLs
        if image_url.startswith('data:'):
            # Already a data URL, extract the base64 content
            parts = image_url.split(',', 1)
            if len(parts) != 2:
                return None
            
            image_bytes = base64.b64decode(parts[1])
            
            # Check size limit
            if len(image_bytes) > MAX_IMAGE_SIZE:
                print(f"Image too large: {len(image_bytes)} bytes (max {MAX_IMAGE_SIZE})")
                return None
            
            # Determine extension from mime type
            mime_part = parts[0]
            if 'png' in mime_part:
                extension = 'png'
            elif 'gif' in mime_part:
                extension = 'gif'
            elif 'webp' in mime_part:
                extension = 'webp'
            else:
                extension = 'jpg'
        else:
            # Download from URL
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                async with session.get(image_url, headers=headers) as response:
                    if response.status != 200:
                        print(f"Failed to download image: HTTP {response.status}")
                        return None
                    
                    # Check content length before downloading
                    content_length = response.headers.get('Content-Length')
                    if content_length and int(content_length) > MAX_IMAGE_SIZE:
                        print(f"Image too large: {content_length} bytes (max {MAX_IMAGE_SIZE})")
                        return None
                    
                    content_type = response.headers.get('Content-Type', '')
                    image_bytes = await response.read()
                    
                    # Check actual size after download
                    if len(image_bytes) > MAX_IMAGE_SIZE:
                        print(f"Image too large: {len(image_bytes)} bytes (max {MAX_IMAGE_SIZE})")
                        return None
                    
                    # Determine extension from content type
                    if 'png' in content_type:
                        extension = 'png'
                    elif 'gif' in content_type:
                        extension = 'gif'
                    elif 'webp' in content_type:
                        extension = 'webp'
                    else:
                        extension = 'jpg'
        
        # Verify it's a valid image using PIL
        try:
            img = Image.open(BytesIO(image_bytes))
            img.verify()  # Verify it's a valid image
            # Re-open after verify (verify closes the file)
            img = Image.open(BytesIO(image_bytes))
            actual_width, actual_height = img.size
        except Exception as e:
            print(f"Invalid image data from {image_url}: {e}")
            return None
        
        # Use actual dimensions if not specified
        final_width = width if width > 0 else actual_width
        final_height = height if height > 0 else actual_height
        
        # Generate file ID and save
        file_id = generate_file_id()
        filename = f'{file_id}.{extension}'
        file_path = os.path.join(FILES_DIR, filename)
        
        # Save the image
        os.makedirs(FILES_DIR, exist_ok=True)
        with open(file_path, 'wb') as f:
            f.write(image_bytes)
        
        # Create data URL for canvas
        data_url = f"data:image/{extension};base64,{base64.b64encode(image_bytes).decode('utf-8')}"
        
        return {
            'file_id': file_id,
            'filename': filename,
            'url': f'http://localhost:{DEFAULT_PORT}/api/file/{filename}',
            'width': final_width,
            'height': final_height,
            'dataURL': data_url,
            'mimeType': f'image/{extension}'
        }
        
    except Exception as e:
        print(f"Error downloading image from {image_url}: {e}")
        return None
