# routers/website_router.py
"""
Website Import Router - API endpoints for importing websites into Jaaz canvas.
"""

import base64
import os
import traceback
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from PIL import Image
from io import BytesIO
from pydantic import BaseModel, Field

from services.config_service import FILES_DIR
from services.website_import_service import (
    WebsiteElement,
    website_import_service,
)
from tools.utils.image_canvas_utils import (
    generate_file_id,
    download_image_to_canvas_element,
)

router = APIRouter(prefix="/api/website")


class WebsiteImportRequest(BaseModel):
    """Request model for importing a website."""
    url: str = Field(..., description="The URL of the website to import")
    viewport_width: int = Field(default=1280, description="Viewport width for rendering")
    viewport_height: int = Field(default=800, description="Viewport height for rendering")
    include_text: bool = Field(default=False, description="Whether to include text elements")
    include_images: bool = Field(default=True, description="Whether to include image elements")
    include_videos: bool = Field(default=True, description="Whether to include video elements")


class CanvasElementResponse(BaseModel):
    """Response model for a single canvas element."""
    id: str
    type: str  # 'image', 'text', 'video', 'embeddable'
    x: float
    y: float
    width: float
    height: float
    content: Optional[str] = None  # For text elements
    file_url: Optional[str] = None  # For image/video elements
    file_id: Optional[str] = None  # For image elements
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WebsiteImportResponse(BaseModel):
    """Response model for website import."""
    success: bool
    url: str
    title: str
    elements: List[CanvasElementResponse]
    screenshot_url: Optional[str] = None
    viewport_width: int
    viewport_height: int
    error: Optional[str] = None


@router.post("/import")
async def import_website(request: WebsiteImportRequest) -> WebsiteImportResponse:
    """
    Import a website and convert it to canvas elements.
    
    This endpoint:
    1. Fetches the website using Playwright
    2. Extracts visual elements (images, text, videos)
    3. Downloads images and saves them locally
    4. Returns canvas-ready elements
    """
    try:
        # Fetch and parse the website
        result = await website_import_service.fetch_website(
            url=request.url,
            viewport_width=request.viewport_width,
            viewport_height=request.viewport_height
        )
        
        if result.error:
            return WebsiteImportResponse(
                success=False,
                url=request.url,
                title="",
                elements=[],
                viewport_width=request.viewport_width,
                viewport_height=request.viewport_height,
                error=result.error
            )
        
        # Convert parsed elements to canvas elements
        canvas_elements: List[CanvasElementResponse] = []
        
        for element in result.elements:
            # Skip elements based on filter settings
            if element.type in ('text', 'heading') and not request.include_text:
                continue
            if element.type == 'image' and not request.include_images:
                continue
            if element.type == 'video' and not request.include_videos:
                continue
            
            canvas_element = await _convert_to_canvas_element(element, request.url)
            if canvas_element:
                canvas_elements.append(canvas_element)
        
        # Save screenshot if available
        screenshot_url = None
        if result.screenshot_base64:
            screenshot_url = await _save_screenshot(result.screenshot_base64)
        
        return WebsiteImportResponse(
            success=True,
            url=request.url,
            title=result.title,
            elements=canvas_elements,
            screenshot_url=screenshot_url,
            viewport_width=result.viewport_width,
            viewport_height=result.viewport_height
        )
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to import website: {str(e)}")


async def _convert_to_canvas_element(
    element: WebsiteElement,
    base_url: str
) -> Optional[CanvasElementResponse]:
    """Convert a WebsiteElement to a CanvasElementResponse."""
    element_id = str(uuid.uuid4())
    
    if element.type == 'image':
        # Download and save the image
        image_url = element.content
        if not image_url:
            return None
        
        try:
            # Use existing image download utility
            image_data = await download_image_to_canvas_element(
                image_url=image_url,
                x=element.x,
                y=element.y,
                width=element.width,
                height=element.height
            )
            
            if image_data:
                return CanvasElementResponse(
                    id=element_id,
                    type='image',
                    x=element.x,
                    y=element.y,
                    width=image_data.get('width', element.width),
                    height=image_data.get('height', element.height),
                    file_url=image_data.get('url'),
                    file_id=image_data.get('file_id'),
                    metadata={
                        'alt': element.metadata.get('alt', ''),
                        'original_url': image_url,
                        'is_background': element.metadata.get('is_background', False)
                    }
                )
        except Exception as e:
            print(f"Failed to download image {image_url}: {e}")
            # Return element with original URL if download fails
            return CanvasElementResponse(
                id=element_id,
                type='image',
                x=element.x,
                y=element.y,
                width=element.width,
                height=element.height,
                file_url=image_url,
                metadata={
                    'alt': element.metadata.get('alt', ''),
                    'original_url': image_url,
                    'download_failed': True
                }
            )
    
    elif element.type in ('text', 'heading'):
        return CanvasElementResponse(
            id=element_id,
            type='text',
            x=element.x,
            y=element.y,
            width=element.width,
            height=element.height,
            content=element.content,
            metadata={
                'font_size': element.font_size,
                'font_family': element.font_family,
                'color': element.color,
                'is_heading': element.type == 'heading',
                'heading_level': element.metadata.get('level'),
                'font_weight': element.metadata.get('font_weight', 'normal')
            }
        )
    
    elif element.type == 'video':
        return CanvasElementResponse(
            id=element_id,
            type='video',
            x=element.x,
            y=element.y,
            width=element.width,
            height=element.height,
            file_url=element.content,
            metadata={
                'poster': element.metadata.get('poster', ''),
                'is_embed': element.metadata.get('is_embed', False),
                'original_url': element.content
            }
        )
    
    return None


async def _save_screenshot(screenshot_base64: str) -> str:
    """Save a screenshot and return its URL."""
    from common import DEFAULT_PORT
    
    # Maximum file size: 10MB
    MAX_SCREENSHOT_SIZE = 10 * 1024 * 1024
    
    # Validate and decode base64
    try:
        screenshot_bytes = base64.b64decode(screenshot_base64)
    except Exception as e:
        raise ValueError(f"Invalid base64 data: {e}")
    
    # Check file size
    if len(screenshot_bytes) > MAX_SCREENSHOT_SIZE:
        raise ValueError(f"Screenshot too large: {len(screenshot_bytes)} bytes (max {MAX_SCREENSHOT_SIZE})")
    
    # Verify it's a valid PNG image
    try:
        img = Image.open(BytesIO(screenshot_bytes))
        img.verify()  # Verify it's a valid image
    except Exception as e:
        raise ValueError(f"Invalid image data: {e}")
    
    file_id = generate_file_id()
    file_path = os.path.join(FILES_DIR, f'{file_id}.png')
    
    # Ensure directory exists
    os.makedirs(FILES_DIR, exist_ok=True)
    
    # Save the screenshot
    with open(file_path, 'wb') as f:
        f.write(screenshot_bytes)
    
    return f'http://localhost:{DEFAULT_PORT}/api/file/{file_id}.png'


@router.post("/preview")
async def preview_website(request: WebsiteImportRequest) -> Dict[str, Any]:
    """
    Preview a website by taking a screenshot without extracting elements.
    Useful for quick previews before full import.
    """
    try:
        result = await website_import_service.fetch_website(
            url=request.url,
            viewport_width=request.viewport_width,
            viewport_height=request.viewport_height
        )
        
        if result.error:
            raise HTTPException(status_code=400, detail=result.error)
        
        screenshot_url = None
        if result.screenshot_base64:
            screenshot_url = await _save_screenshot(result.screenshot_base64)
        
        return {
            "success": True,
            "url": request.url,
            "title": result.title,
            "screenshot_url": screenshot_url,
            "viewport_width": result.viewport_width,
            "viewport_height": result.viewport_height,
            "element_counts": {
                "images": len([e for e in result.elements if e.type == 'image']),
                "text": len([e for e in result.elements if e.type in ('text', 'heading')]),
                "videos": len([e for e in result.elements if e.type == 'video'])
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to preview website: {str(e)}")
