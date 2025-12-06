# services/website_import_service.py
"""
Website Import Service - Fetches and parses websites to extract design elements
for automatic rebuilding on the Jaaz canvas.
"""

import base64
import ipaddress
import socket
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse


# Constants
DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
MAX_VIEWPORT_HEIGHT = 4000  # Maximum height for captured viewport

# Private IP ranges to block (SSRF protection)
BLOCKED_IP_RANGES = [
    ipaddress.ip_network('127.0.0.0/8'),      # Loopback
    ipaddress.ip_network('10.0.0.0/8'),       # Private network
    ipaddress.ip_network('172.16.0.0/12'),    # Private network  
    ipaddress.ip_network('192.168.0.0/16'),   # Private network
    ipaddress.ip_network('169.254.0.0/16'),   # Link-local
    ipaddress.ip_network('::1/128'),          # IPv6 loopback
    ipaddress.ip_network('fc00::/7'),         # IPv6 private
    ipaddress.ip_network('fe80::/10'),        # IPv6 link-local
]


@dataclass
class WebsiteElement:
    """Represents a parsed element from a website."""
    type: str  # 'image', 'text', 'heading', 'container', 'video'
    content: Optional[str] = None  # text content or image URL/base64
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    font_size: Optional[int] = None
    font_family: Optional[str] = None
    color: Optional[str] = None
    background_color: Optional[str] = None
    border: Optional[str] = None
    z_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WebsiteParseResult:
    """Result of parsing a website."""
    url: str
    title: str
    elements: List[WebsiteElement]
    viewport_width: int
    viewport_height: int
    screenshot_base64: Optional[str] = None
    error: Optional[str] = None


class WebsiteImportService:
    """Service for importing and parsing websites."""
    
    def __init__(self):
        pass
    
    def _is_private_ip(self, hostname: str) -> bool:
        """Check if hostname resolves to a private/blocked IP address."""
        try:
            # Resolve hostname to IP addresses
            addr_info = socket.getaddrinfo(hostname, None)
            for family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                try:
                    ip = ipaddress.ip_address(ip_str)
                    for blocked_range in BLOCKED_IP_RANGES:
                        if ip in blocked_range:
                            return True
                except ValueError:
                    continue
            return False
        except socket.gaierror:
            # DNS resolution failed - allow the request to proceed
            # and let Playwright handle the error
            return False
    
    async def fetch_website(
        self,
        url: str,
        viewport_width: int = 1280,
        viewport_height: int = 800
    ) -> WebsiteParseResult:
        """
        Fetch and parse a website to extract design elements.
        
        Args:
            url: The website URL to import
            viewport_width: Width of the viewport for rendering
            viewport_height: Height of the viewport for rendering
            
        Returns:
            WebsiteParseResult containing parsed elements
        """
        try:
            # Validate URL
            parsed_url = urlparse(url)
            if not parsed_url.scheme:
                url = f"https://{url}"
                parsed_url = urlparse(url)
            elif parsed_url.scheme not in ('http', 'https'):
                return WebsiteParseResult(
                    url=url,
                    title="",
                    elements=[],
                    viewport_width=viewport_width,
                    viewport_height=viewport_height,
                    error="Invalid URL scheme. Only HTTP and HTTPS are supported."
                )
            
            # SSRF protection: Block requests to private/internal networks
            hostname = parsed_url.hostname or ''
            if hostname.lower() in ('localhost', '127.0.0.1', '::1'):
                return WebsiteParseResult(
                    url=url,
                    title="",
                    elements=[],
                    viewport_width=viewport_width,
                    viewport_height=viewport_height,
                    error="Access to localhost/internal addresses is not allowed."
                )
            
            if self._is_private_ip(hostname):
                return WebsiteParseResult(
                    url=url,
                    title="",
                    elements=[],
                    viewport_width=viewport_width,
                    viewport_height=viewport_height,
                    error="Access to private/internal network addresses is not allowed."
                )
            
            # Try using Playwright for full rendering
            result = await self._fetch_with_playwright(
                url, viewport_width, viewport_height
            )
            
            return result
            
        except Exception as e:
            traceback.print_exc()
            return WebsiteParseResult(
                url=url,
                title="",
                elements=[],
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                error=f"Failed to fetch website: {str(e)}"
            )
    
    async def _fetch_with_playwright(
        self,
        url: str,
        viewport_width: int,
        viewport_height: int
    ) -> WebsiteParseResult:
        """
        Fetch website using Playwright for full JavaScript rendering.
        """
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            
            try:
                context = await browser.new_context(
                    viewport={'width': viewport_width, 'height': viewport_height},
                    user_agent=DEFAULT_USER_AGENT
                )
                
                page = await context.new_page()
                
                # Navigate to the page
                await page.goto(url, wait_until='networkidle', timeout=30000)
                
                # Get page title
                title = await page.title()
                
                # Take a screenshot
                screenshot_bytes = await page.screenshot(full_page=False, type='png')
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                
                # Extract elements from the page
                elements = await self._extract_elements_from_page(page, url)
                
                # Get scroll height for full page
                scroll_height = await page.evaluate('document.documentElement.scrollHeight')
                
                return WebsiteParseResult(
                    url=url,
                    title=title,
                    elements=elements,
                    viewport_width=viewport_width,
                    viewport_height=min(scroll_height, MAX_VIEWPORT_HEIGHT),
                    screenshot_base64=screenshot_base64
                )
                
            finally:
                await browser.close()
    
    async def _extract_elements_from_page(
        self,
        page: Any,
        base_url: str
    ) -> List[WebsiteElement]:
        """
        Extract visual elements from a Playwright page.
        """
        elements: List[WebsiteElement] = []
        
        # Extract images
        image_elements = await self._extract_images(page, base_url)
        elements.extend(image_elements)
        
        # Extract text elements (headings and paragraphs)
        text_elements = await self._extract_text_elements(page)
        elements.extend(text_elements)
        
        # Extract videos
        video_elements = await self._extract_videos(page, base_url)
        elements.extend(video_elements)
        
        # Sort elements by position (top to bottom, left to right)
        elements.sort(key=lambda e: (e.y, e.x))
        
        return elements
    
    async def _extract_images(
        self,
        page: Any,
        base_url: str
    ) -> List[WebsiteElement]:
        """Extract image elements from the page."""
        elements: List[WebsiteElement] = []
        
        # Get all img elements with their positions
        images_data = await page.evaluate('''() => {
            const images = document.querySelectorAll('img');
            const result = [];
            
            images.forEach((img) => {
                const rect = img.getBoundingClientRect();
                
                // Skip invisible images
                if (rect.width < 20 || rect.height < 20) return;
                if (rect.top < 0 || rect.left < 0) return;
                
                const computedStyle = window.getComputedStyle(img);
                if (computedStyle.display === 'none' || computedStyle.visibility === 'hidden') return;
                
                result.push({
                    src: img.src || img.dataset.src || '',
                    alt: img.alt || '',
                    x: rect.left + window.scrollX,
                    y: rect.top + window.scrollY,
                    width: rect.width,
                    height: rect.height,
                    zIndex: parseInt(computedStyle.zIndex) || 0
                });
            });
            
            // Also get background images from divs
            const divsWithBg = document.querySelectorAll('div, section, header, footer');
            divsWithBg.forEach((div) => {
                const computedStyle = window.getComputedStyle(div);
                const bgImage = computedStyle.backgroundImage;
                
                if (bgImage && bgImage !== 'none') {
                    const rect = div.getBoundingClientRect();
                    if (rect.width < 50 || rect.height < 50) return;
                    
                    const urlMatch = bgImage.match(/url\\(['"]?([^'"')]+)['"]?\\)/);
                    if (urlMatch) {
                        result.push({
                            src: urlMatch[1],
                            alt: '',
                            x: rect.left + window.scrollX,
                            y: rect.top + window.scrollY,
                            width: rect.width,
                            height: rect.height,
                            zIndex: parseInt(computedStyle.zIndex) || 0,
                            isBackground: true
                        });
                    }
                }
            });
            
            return result;
        }''')
        
        for img_data in images_data:
            src = img_data.get('src', '')
            if not src:
                continue
            
            # Make URL absolute
            if not src.startswith(('http://', 'https://', 'data:')):
                src = urljoin(base_url, src)
            
            elements.append(WebsiteElement(
                type='image',
                content=src,
                x=img_data.get('x', 0),
                y=img_data.get('y', 0),
                width=img_data.get('width', 0),
                height=img_data.get('height', 0),
                z_index=img_data.get('zIndex', 0),
                metadata={
                    'alt': img_data.get('alt', ''),
                    'is_background': img_data.get('isBackground', False)
                }
            ))
        
        return elements
    
    async def _extract_text_elements(
        self,
        page: Any
    ) -> List[WebsiteElement]:
        """Extract text elements (headings and paragraphs) from the page."""
        elements: List[WebsiteElement] = []
        
        # Extract headings and important text
        text_data = await page.evaluate('''() => {
            const selectors = 'h1, h2, h3, h4, h5, h6, p, span.title, span.heading, div.title, div.heading';
            const textElements = document.querySelectorAll(selectors);
            const result = [];
            
            textElements.forEach((el) => {
                const text = el.innerText?.trim() || '';
                if (!text || text.length < 2) return;
                
                const rect = el.getBoundingClientRect();
                if (rect.width < 20 || rect.height < 10) return;
                if (rect.top < 0 || rect.left < 0) return;
                
                const computedStyle = window.getComputedStyle(el);
                if (computedStyle.display === 'none' || computedStyle.visibility === 'hidden') return;
                
                const tagName = el.tagName.toLowerCase();
                const isHeading = tagName.startsWith('h') && tagName.length === 2;
                
                result.push({
                    text: text.substring(0, 500),  // Limit text length
                    type: isHeading ? 'heading' : 'text',
                    level: isHeading ? parseInt(tagName[1]) : null,
                    x: rect.left + window.scrollX,
                    y: rect.top + window.scrollY,
                    width: rect.width,
                    height: rect.height,
                    fontSize: parseInt(computedStyle.fontSize) || 16,
                    fontFamily: computedStyle.fontFamily || 'sans-serif',
                    color: computedStyle.color || '#000000',
                    fontWeight: computedStyle.fontWeight || 'normal',
                    zIndex: parseInt(computedStyle.zIndex) || 0
                });
            });
            
            return result;
        }''')
        
        for text_item in text_data:
            elements.append(WebsiteElement(
                type=text_item.get('type', 'text'),
                content=text_item.get('text', ''),
                x=text_item.get('x', 0),
                y=text_item.get('y', 0),
                width=text_item.get('width', 0),
                height=text_item.get('height', 0),
                font_size=text_item.get('fontSize', 16),
                font_family=text_item.get('fontFamily', 'sans-serif'),
                color=text_item.get('color', '#000000'),
                z_index=text_item.get('zIndex', 0),
                metadata={
                    'level': text_item.get('level'),
                    'font_weight': text_item.get('fontWeight', 'normal')
                }
            ))
        
        return elements
    
    async def _extract_videos(
        self,
        page: Any,
        base_url: str
    ) -> List[WebsiteElement]:
        """Extract video elements from the page."""
        elements: List[WebsiteElement] = []
        
        videos_data = await page.evaluate('''() => {
            const videos = document.querySelectorAll('video');
            const result = [];
            
            videos.forEach((video) => {
                const rect = video.getBoundingClientRect();
                if (rect.width < 50 || rect.height < 30) return;
                
                const src = video.src || video.querySelector('source')?.src || '';
                const poster = video.poster || '';
                
                result.push({
                    src: src,
                    poster: poster,
                    x: rect.left + window.scrollX,
                    y: rect.top + window.scrollY,
                    width: rect.width,
                    height: rect.height
                });
            });
            
            // Also look for iframes (YouTube, Vimeo, etc.)
            const iframes = document.querySelectorAll('iframe');
            iframes.forEach((iframe) => {
                const src = iframe.src || '';
                if (!src.includes('youtube') && !src.includes('vimeo')) return;
                
                const rect = iframe.getBoundingClientRect();
                if (rect.width < 50 || rect.height < 30) return;
                
                result.push({
                    src: src,
                    poster: '',
                    x: rect.left + window.scrollX,
                    y: rect.top + window.scrollY,
                    width: rect.width,
                    height: rect.height,
                    isEmbed: true
                });
            });
            
            return result;
        }''')
        
        for video_data in videos_data:
            src = video_data.get('src', '')
            if not src:
                continue
            
            # Make URL absolute
            if not src.startswith(('http://', 'https://')):
                src = urljoin(base_url, src)
            
            elements.append(WebsiteElement(
                type='video',
                content=src,
                x=video_data.get('x', 0),
                y=video_data.get('y', 0),
                width=video_data.get('width', 320),
                height=video_data.get('height', 180),
                metadata={
                    'poster': video_data.get('poster', ''),
                    'is_embed': video_data.get('isEmbed', False)
                }
            ))
        
        return elements


# Singleton instance
website_import_service = WebsiteImportService()
