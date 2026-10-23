import type { ReactNode } from 'react'
import { Accordion } from '../arc/accordion/accordion'

/** A fold-away detail, drawn by Arc's accordion instead of the browser's own
 *  triangle. One item, closed unless asked: the panels that had a `<details>`
 *  keep the same reading order and gain its motion and focus handling. */
export function Disclosure({ title, open = false, children }: { title: string; open?: boolean; children: ReactNode }) {
  return <Accordion items={[{ title, content: children }]} defaultOpen={open ? 0 : -1} />
}
