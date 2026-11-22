import { lazy, Suspense } from 'react'

/** An answer is markdown. The pipeline that draws it (react-markdown, the table
 *  and list plugins, the word-by-word entrance) is a large vendor chunk that the
 *  Ask landing never needs, so it is loaded the first time an answer is on the
 *  screen. Until it arrives the text is already readable as plain paragraphs, in
 *  the same box, so nothing jumps when the real renderer replaces it. */
const MarkdownBody = lazy(() => import('./MarkdownBody').then((one) => ({ default: one.Markdown })))

/** Start fetching the renderer (the shell does it when idle, and on first use). */
export const prefetchMarkdown = () => void import('./MarkdownBody')

export function Markdown({ text, live = false }: { text: string; live?: boolean }) {
  return (
    <Suspense fallback={<div className="md"><p style={{ whiteSpace: 'pre-wrap' }}>{text}</p></div>}>
      <MarkdownBody text={text} live={live} />
    </Suspense>
  )
}
