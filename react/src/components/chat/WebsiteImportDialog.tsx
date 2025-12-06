// components/chat/WebsiteImportDialog.tsx
// Dialog component for importing websites into the canvas

import { useState } from 'react'
import { toast } from 'sonner'
import { Globe, Loader2, Image as ImageIcon, Type, Video, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { previewWebsite, importWebsite, WebsiteImportResponse } from '@/api/website'

interface WebsiteImportDialogProps {
  onImportComplete: (result: WebsiteImportResponse) => void
}

export function WebsiteImportDialog({
  onImportComplete,
}: WebsiteImportDialogProps) {
  const [open, setOpen] = useState(false)
  const [url, setUrl] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isPreviewing, setIsPreviewing] = useState(false)
  const [previewData, setPreviewData] = useState<{
    screenshot_url?: string
    title: string
    element_counts: {
      images: number
      text: number
      videos: number
    }
  } | null>(null)

  // Import options
  const [includeImages, setIncludeImages] = useState(true)
  const [includeText, setIncludeText] = useState(false)
  const [includeVideos, setIncludeVideos] = useState(true)

  const handlePreview = async () => {
    if (!url.trim()) {
      toast.error('Please enter a website URL')
      return
    }

    setIsPreviewing(true)
    try {
      const result = await previewWebsite({ url })
      setPreviewData({
        screenshot_url: result.screenshot_url,
        title: result.title,
        element_counts: result.element_counts,
      })
    } catch (error) {
      console.error('Preview error:', error)
      toast.error('Failed to preview website', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    } finally {
      setIsPreviewing(false)
    }
  }

  const handleImport = async () => {
    if (!url.trim()) {
      toast.error('Please enter a website URL')
      return
    }

    setIsLoading(true)
    try {
      const result = await importWebsite({
        url,
        include_images: includeImages,
        include_text: includeText,
        include_videos: includeVideos,
      })

      if (result.success) {
        toast.success(`Website imported successfully!`, {
          description: `Imported ${result.elements.length} elements from "${result.title}"`,
        })
        onImportComplete(result)
        setOpen(false)
        resetState()
      } else {
        toast.error('Failed to import website', {
          description: result.error || 'Unknown error',
        })
      }
    } catch (error) {
      console.error('Import error:', error)
      toast.error('Failed to import website', {
        description: error instanceof Error ? error.message : 'Unknown error',
      })
    } finally {
      setIsLoading(false)
    }
  }

  const resetState = () => {
    setUrl('')
    setPreviewData(null)
    setIncludeImages(true)
    setIncludeText(false)
    setIncludeVideos(true)
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <Globe className="size-4" />
          <span className="hidden sm:inline">Import Website</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Globe className="size-5" />
            Import Website Design
          </DialogTitle>
          <DialogDescription>
            Enter a website URL to import its design elements into your canvas.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* URL Input */}
          <div className="space-y-2">
            <Label htmlFor="website-url">Website URL</Label>
            <div className="flex gap-2">
              <Input
                id="website-url"
                placeholder="https://example.com"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    handlePreview()
                  }
                }}
              />
              <Button
                variant="outline"
                onClick={handlePreview}
                disabled={isPreviewing || !url.trim()}
              >
                {isPreviewing ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  'Preview'
                )}
              </Button>
            </div>
          </div>

          {/* Preview */}
          {previewData && (
            <div className="space-y-3 rounded-lg border p-3">
              <div className="flex items-center justify-between">
                <h4 className="font-medium text-sm truncate">
                  {previewData.title || 'Untitled'}
                </h4>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPreviewData(null)}
                >
                  <X className="size-4" />
                </Button>
              </div>

              {previewData.screenshot_url && (
                <div className="relative aspect-video rounded-md overflow-hidden bg-muted">
                  <img
                    src={previewData.screenshot_url}
                    alt="Website preview"
                    className="w-full h-full object-cover object-top"
                  />
                </div>
              )}

              <div className="flex gap-4 text-sm text-muted-foreground">
                <span className="flex items-center gap-1">
                  <ImageIcon className="size-3" />
                  {previewData.element_counts.images} images
                </span>
                <span className="flex items-center gap-1">
                  <Type className="size-3" />
                  {previewData.element_counts.text} text
                </span>
                <span className="flex items-center gap-1">
                  <Video className="size-3" />
                  {previewData.element_counts.videos} videos
                </span>
              </div>
            </div>
          )}

          {/* Import Options */}
          <div className="space-y-3">
            <Label>Import Options</Label>
            <div className="flex flex-wrap gap-4">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="include-images"
                  checked={includeImages}
                  onCheckedChange={(checked) =>
                    setIncludeImages(checked as boolean)
                  }
                />
                <label
                  htmlFor="include-images"
                  className="text-sm cursor-pointer flex items-center gap-1"
                >
                  <ImageIcon className="size-3" />
                  Images
                </label>
              </div>

              <div className="flex items-center space-x-2">
                <Checkbox
                  id="include-text"
                  checked={includeText}
                  onCheckedChange={(checked) =>
                    setIncludeText(checked as boolean)
                  }
                />
                <label
                  htmlFor="include-text"
                  className="text-sm cursor-pointer flex items-center gap-1"
                >
                  <Type className="size-3" />
                  Text
                </label>
              </div>

              <div className="flex items-center space-x-2">
                <Checkbox
                  id="include-videos"
                  checked={includeVideos}
                  onCheckedChange={(checked) =>
                    setIncludeVideos(checked as boolean)
                  }
                />
                <label
                  htmlFor="include-videos"
                  className="text-sm cursor-pointer flex items-center gap-1"
                >
                  <Video className="size-3" />
                  Videos
                </label>
              </div>
            </div>
          </div>

          {/* Import Button */}
          <Button
            className="w-full"
            onClick={handleImport}
            disabled={isLoading || !url.trim()}
          >
            {isLoading ? (
              <>
                <Loader2 className="size-4 animate-spin mr-2" />
                Importing...
              </>
            ) : (
              <>
                <Globe className="size-4 mr-2" />
                Import Website
              </>
            )}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default WebsiteImportDialog
