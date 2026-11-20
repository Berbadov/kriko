import { SHELF_SPRITES } from './shelfSprites'

/** The product pixel library, drawn once for every screen.
 *
 *  The shelf on the home screen used to be the only place these symbols were
 *  defined, so a list or a comparison column could not show one: `<use>` found
 *  no symbol and drew nothing. One hidden `<svg>` at the shell's root makes the
 *  library available everywhere, and costs one copy.
 */
export function PixelSprites() {
  return <svg width="0" height="0" style={{ position: 'absolute' }} aria-hidden="true" dangerouslySetInnerHTML={{ __html: SHELF_SPRITES }} />
}

import { glyphFor } from './productGlyphs'

export function ProductGlyph({ name, size = 26 }: { name: string; size?: number }) {
  const sprite = glyphFor(name)
  if (!sprite) return null
  return (
    <svg className="product-glyph" viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" focusable="false">
      <use href={`#${sprite}`} />
    </svg>
  )
}
