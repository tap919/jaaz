// api/website.ts
// API functions for website import functionality

export interface WebsiteImportRequest {
  url: string
  viewport_width?: number
  viewport_height?: number
  include_text?: boolean
  include_images?: boolean
  include_videos?: boolean
}

export interface CanvasElement {
  id: string
  type: 'image' | 'text' | 'video'
  x: number
  y: number
  width: number
  height: number
  content?: string // For text elements
  file_url?: string // For image/video elements
  file_id?: string // For image elements
  metadata?: Record<string, unknown>
}

export interface WebsiteImportResponse {
  success: boolean
  url: string
  title: string
  elements: CanvasElement[]
  screenshot_url?: string
  viewport_width: number
  viewport_height: number
  error?: string
}

export interface WebsitePreviewResponse {
  success: boolean
  url: string
  title: string
  screenshot_url?: string
  viewport_width: number
  viewport_height: number
  element_counts: {
    images: number
    text: number
    videos: number
  }
}

/**
 * Import a website and convert it to canvas elements
 */
export async function importWebsite(
  request: WebsiteImportRequest
): Promise<WebsiteImportResponse> {
  const response = await fetch('/api/website/import', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      url: request.url,
      viewport_width: request.viewport_width ?? 1280,
      viewport_height: request.viewport_height ?? 800,
      include_text: request.include_text ?? false,
      include_images: request.include_images ?? true,
      include_videos: request.include_videos ?? true,
    }),
  })

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.detail || 'Failed to import website')
  }

  return await response.json()
}

/**
 * Preview a website without full import
 */
export async function previewWebsite(
  request: WebsiteImportRequest
): Promise<WebsitePreviewResponse> {
  const response = await fetch('/api/website/preview', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      url: request.url,
      viewport_width: request.viewport_width ?? 1280,
      viewport_height: request.viewport_height ?? 800,
    }),
  })

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}))
    throw new Error(errorData.detail || 'Failed to preview website')
  }

  return await response.json()
}
