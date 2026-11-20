import '@fontsource/atkinson-hyperlegible/400.css'
import '@fontsource/atkinson-hyperlegible/700.css'
import { useCallback, useState } from 'react'

/** The text font: the app's own, or the accessibility face. The choice is kept on
 *  this computer. base.css reads `data-font='atkinson'` on the root element. */
export type TextFont = 'default' | 'atkinson'

const KEY = 'kriko.font'

export function readTextFont(): TextFont {
  try {
    return globalThis.localStorage?.getItem(KEY) === 'atkinson' ? 'atkinson' : 'default'
  } catch {
    return 'default'
  }
}

export function applyTextFont(font: TextFont) {
  if (typeof document === 'undefined') return
  if (font === 'atkinson') document.documentElement.dataset.font = 'atkinson'
  else delete document.documentElement.dataset.font
}

function storeTextFont(font: TextFont) {
  try {
    globalThis.localStorage?.setItem(KEY, font)
  } catch {
    // A private window cannot keep it. The choice still holds until the reload.
  }
}

// Applied when the module loads, so the saved face is in place before the first
// screen is drawn, not only when Settings is open.
applyTextFont(readTextFont())

export function useTextFont(): [TextFont, (font: TextFont) => void] {
  const [font, setFontState] = useState<TextFont>(readTextFont)
  const setFont = useCallback((next: TextFont) => {
    setFontState(next)
    storeTextFont(next)
    applyTextFont(next)
  }, [])
  return [font, setFont]
}
