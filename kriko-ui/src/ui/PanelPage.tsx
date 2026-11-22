import type { ReactNode } from 'react'

/** A panel built to sit in a drawer, shown as a whole page. The panel keeps its
 *  own body (`.panel-body`); this gives it the screen's title and margins. */
export function PanelPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="k-screen panel-page" aria-label={title}>
      <header className="k-head">
        <h1 className="k-title">{title}</h1>
      </header>
      {children}
    </section>
  )
}
