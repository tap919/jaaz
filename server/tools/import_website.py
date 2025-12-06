# tools/import_website.py
"""
Website Import Tool - Allows the AI agent to import websites into the canvas.
"""

from pydantic import BaseModel, Field

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

from services.website_import_service import website_import_service
from services.websocket_service import send_to_websocket, broadcast_session_update
from tools.utils.image_canvas_utils import (
    canvas_lock_manager,
    generate_file_id,
    download_image_to_canvas_element,
)
from services.db_service import db_service
import json
import time
import random


class WebsiteImportInput(BaseModel):
    """Input schema for website import tool."""
    url: str = Field(..., description="The URL of the website to import")
    include_images: bool = Field(
        default=True,
        description="Whether to include images from the website"
    )
    include_text: bool = Field(
        default=False,
        description="Whether to include text elements from the website"
    )
    include_videos: bool = Field(
        default=True,
        description="Whether to include video elements from the website"
    )


@tool(
    "import_website",
    description="""
Import a website design into the canvas. This tool fetches a website, 
extracts its visual elements (images, text, videos), and adds them to the canvas.

Use this tool when the user wants to:
- Import an existing website design
- Clone or recreate a website layout
- Extract images and content from a website
- Analyze and rebuild a website design

The tool will download images and position them on the canvas automatically.
""",
    args_schema=WebsiteImportInput
)
async def import_website_tool(
    url: str,
    include_images: bool,
    include_text: bool,
    include_videos: bool,
    config: RunnableConfig,
) -> str:
    """
    Import a website into the canvas.
    
    Args:
        url: The URL of the website to import
        include_images: Whether to include images
        include_text: Whether to include text elements
        include_videos: Whether to include video elements
        config: LangChain runnable config containing session and canvas info
        
    Returns:
        A message describing the import result
    """
    # Get context from config
    configurable = config.get("configurable", {})
    canvas_id = configurable.get("canvas_id", "")
    session_id = configurable.get("session_id", "")
    
    if not canvas_id or not session_id:
        return "Error: Canvas ID or Session ID not found in context."
    
    # Notify user that import is starting
    await send_to_websocket(session_id, {
        'type': 'website_import_start',
        'message': f'🌐 Starting to import website: {url}'
    })
    
    try:
        # Fetch and parse the website
        result = await website_import_service.fetch_website(
            url=url,
            viewport_width=1280,
            viewport_height=800
        )
        
        if result.error:
            await send_to_websocket(session_id, {
                'type': 'error',
                'error': f'Failed to import website: {result.error}'
            })
            return f"Error importing website: {result.error}"
        
        # Filter elements based on settings
        elements_to_import = []
        for element in result.elements:
            if element.type == 'image' and include_images:
                elements_to_import.append(element)
            elif element.type in ('text', 'heading') and include_text:
                elements_to_import.append(element)
            elif element.type == 'video' and include_videos:
                elements_to_import.append(element)
        
        if not elements_to_import:
            return f"No elements found to import from {url}. The website may have dynamic content or strict access controls."
        
        # Import elements to canvas
        imported_count = 0
        failed_count = 0
        
        # Use canvas lock for atomic operations
        async with canvas_lock_manager.lock_canvas(canvas_id):
            # Get current canvas data
            canvas = await db_service.get_canvas_data(canvas_id)
            if canvas is None:
                canvas = {'data': {}}
            canvas_data = canvas.get('data', {})
            
            if 'elements' not in canvas_data:
                canvas_data['elements'] = []
            if 'files' not in canvas_data:
                canvas_data['files'] = {}
            
            for element in elements_to_import:
                try:
                    if element.type == 'image' and element.content:
                        # Download and add image to canvas
                        image_data = await download_image_to_canvas_element(
                            image_url=element.content,
                            x=element.x,
                            y=element.y,
                            width=element.width,
                            height=element.height
                        )
                        
                        if image_data:
                            file_id = image_data['file_id']
                            
                            # Create file data for canvas
                            file_data = {
                                'mimeType': image_data['mimeType'],
                                'id': file_id,
                                'dataURL': image_data['dataURL'],
                                'created': int(time.time() * 1000),
                            }
                            
                            # Create image element
                            new_element = {
                                "type": "image",
                                "id": file_id,
                                "x": element.x,
                                "y": element.y,
                                "width": image_data['width'],
                                "height": image_data['height'],
                                "angle": 0,
                                "fileId": file_id,
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
                                "updated": int(time.time() * 1000),
                                "link": None,
                                "locked": False,
                                "status": "saved",
                                "scale": [1, 1],
                                "crop": None,
                            }
                            
                            canvas_data['elements'].append(new_element)
                            canvas_data['files'][file_id] = file_data
                            
                            # Broadcast image added event
                            await broadcast_session_update(session_id, canvas_id, {
                                'type': 'image_generated',
                                'element': new_element,
                                'file': file_data,
                                'image_url': image_data['url'],
                            })
                            
                            imported_count += 1
                        else:
                            failed_count += 1
                    
                    elif element.type in ('text', 'heading') and element.content:
                        # Create text element
                        text_id = generate_file_id()
                        font_size = element.font_size or 16
                        
                        # Determine font size based on heading level
                        if element.type == 'heading':
                            level = element.metadata.get('level', 1)
                            font_size = max(36 - (level - 1) * 4, 16)
                        
                        new_element = {
                            "type": "text",
                            "id": text_id,
                            "x": element.x,
                            "y": element.y,
                            "width": element.width,
                            "height": element.height,
                            "text": element.content,
                            "fontSize": font_size,
                            "fontFamily": 1,  # Excalidraw font family index
                            "textAlign": "left",
                            "verticalAlign": "top",
                            "angle": 0,
                            "strokeColor": element.color or "#000000",
                            "backgroundColor": "transparent",
                            "fillStyle": "solid",
                            "strokeStyle": "solid",
                            "strokeWidth": 1,
                            "roughness": 0,
                            "opacity": 100,
                            "groupIds": [],
                            "seed": int(random.random() * 1000000),
                            "version": 1,
                            "versionNonce": int(random.random() * 1000000),
                            "isDeleted": False,
                            "index": None,
                            "updated": int(time.time() * 1000),
                            "boundElements": None,
                            "frameId": None,
                            "roundness": None,
                            "link": None,
                            "locked": False,
                            "containerId": None,
                            "originalText": element.content,
                            "autoResize": True,
                            "lineHeight": 1.25,
                        }
                        
                        canvas_data['elements'].append(new_element)
                        imported_count += 1
                    
                    elif element.type == 'video' and element.content:
                        # Create video embed element
                        video_id = generate_file_id()
                        
                        new_element = {
                            "type": "embeddable",
                            "id": video_id,
                            "x": element.x,
                            "y": element.y,
                            "width": element.width or 320,
                            "height": element.height or 180,
                            "link": element.content,
                            "angle": 0,
                            "strokeColor": "#000000",
                            "backgroundColor": "transparent",
                            "fillStyle": "solid",
                            "strokeStyle": "solid",
                            "strokeWidth": 1,
                            "roughness": 0,
                            "opacity": 100,
                            "groupIds": [],
                            "seed": int(random.random() * 1000000),
                            "version": 1,
                            "versionNonce": int(random.random() * 1000000),
                            "isDeleted": False,
                            "index": None,
                            "updated": int(time.time() * 1000),
                            "boundElements": None,
                            "frameId": None,
                            "roundness": None,
                            "locked": False,
                        }
                        
                        canvas_data['elements'].append(new_element)
                        
                        # Broadcast video added event
                        await broadcast_session_update(session_id, canvas_id, {
                            'type': 'video_generated',
                            'element': new_element,
                            'video_url': element.content,
                        })
                        
                        imported_count += 1
                        
                except Exception as e:
                    print(f"Error importing element: {e}")
                    failed_count += 1
            
            # Save updated canvas data
            await db_service.save_canvas_data(canvas_id, json.dumps(canvas_data))
        
        # Notify completion
        await send_to_websocket(session_id, {
            'type': 'website_import_complete',
            'message': f'✅ Website import complete! Imported {imported_count} elements.'
        })
        
        result_message = f"Successfully imported website '{result.title}' from {url}. "
        result_message += f"Added {imported_count} elements to the canvas."
        
        if failed_count > 0:
            result_message += f" ({failed_count} elements could not be imported)"
        
        return result_message
        
    except Exception as e:
        error_msg = f"Error importing website: {str(e)}"
        await send_to_websocket(session_id, {
            'type': 'error',
            'error': error_msg
        })
        return error_msg
