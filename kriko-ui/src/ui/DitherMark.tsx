import mark from '../assets/mark.svg'

/** Kriko's mark printed as a dot field — the one ornament the empty chat gets, in
 *  place of a separate "agent orb". The dots are the same print texture the sky is
 *  drawn in, and the mark is clipped out of that raster, so the shape stays exact
 *  at any size. It prints itself once, row by row, and then holds still: the
 *  landing screen shows no animation that repeats. */
export function DitherMark({ height = 64 }: { height?: number }) {
  const width = Math.round(height * 0.72)
  return <span className="dither-mark" style={{ height, width, '--mark': `url("${mark}")` } as React.CSSProperties} aria-hidden="true" />
}
