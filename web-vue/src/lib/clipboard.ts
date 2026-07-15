export async function writeClipboardText(text: string): Promise<void> {
  let clipboardError: unknown
  if (
    typeof window !== 'undefined'
    && window.isSecureContext
    && typeof navigator !== 'undefined'
    && navigator.clipboard?.writeText
  ) {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch (error) {
      clipboardError = error
    }
  }

  if (typeof document === 'undefined') {
    throw clipboardError instanceof Error ? clipboardError : new Error('clipboard is unavailable')
  }

  const scrollX = window.scrollX
  const scrollY = window.scrollY
  const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'readonly')
  textarea.setAttribute('aria-hidden', 'true')
  textarea.style.position = 'fixed'
  textarea.style.top = '0'
  textarea.style.left = '0'
  textarea.style.width = '1px'
  textarea.style.height = '1px'
  textarea.style.opacity = '0'
  textarea.style.pointerEvents = 'none'
  document.body.appendChild(textarea)

  let copied = false
  try {
    textarea.focus({ preventScroll: true })
    textarea.select()
    textarea.setSelectionRange(0, textarea.value.length)
    copied = document.execCommand('copy')
  } finally {
    textarea.remove()
    activeElement?.focus({ preventScroll: true })
    window.scrollTo(scrollX, scrollY)
  }

  if (!copied) {
    throw clipboardError instanceof Error ? clipboardError : new Error('copy failed')
  }
}
