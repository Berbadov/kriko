import { useEffect, useRef, type ComponentPropsWithoutRef } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** An answer is markdown. A bold term is bold, a list is a list, a table is a
 *  table, and a link opens the page it names. Raw HTML in an answer is not
 *  drawn: react-markdown leaves it out unless a plugin allows it.
 *
 *  Words arrive with motion. Each new word rises out of a blur. While the
 *  answer still grows (`live`), the last few words stay a little blurred and
 *  sharpen as newer words land after them. A word on the screen never replays.
 *  When many words arrive at once, they are staggered, and the whole answer
 *  still settles in about a second.
 *
 *  A small rehype pass numbers the words in the parsed tree, so the number does
 *  not depend on the order in which React renders. Code is left whole. */

/** How many trailing words stay blurred while text grows. */
const TAIL = 4
/** The stagger between words that arrive together, and the most it may add up to. */
const STAGGER_MS = 14
const STAGGER_CAP_MS = 1100

interface HastNode {
  type: string
  tagName?: string
  value?: string
  properties?: Record<string, unknown>
  children?: HastNode[]
}

function rehypeWords() {
  return (tree: HastNode) => {
    let count = 0
    const spans: HastNode[] = []
    const walk = (node: HastNode) => {
      if (!node.children) return
      if (node.type === 'element' && (node.tagName === 'code' || node.tagName === 'pre')) return
      const next: HastNode[] = []
      for (const child of node.children) {
        if (child.type === 'text' && child.value) {
          for (const part of child.value.split(/(\s+)/)) {
            if (!part) continue
            if (/^\s+$/.test(part)) {
              next.push({ type: 'text', value: part })
              continue
            }
            const span: HastNode = {
              type: 'element',
              tagName: 'span',
              properties: { className: ['tok'], dataI: count++ },
              children: [{ type: 'text', value: part }],
            }
            spans.push(span)
            next.push(span)
          }
        } else {
          walk(child)
          next.push(child)
        }
      }
      node.children = next
    }
    walk(tree)
    for (const span of spans) if (span.properties) span.properties.dataN = count
  }
}

export function Markdown({ text, live = false }: { text: string; live?: boolean }) {
  // How many words the screen already holds, so only new words play.
  const shown = useRef(0)
  const box = useRef<HTMLDivElement>(null)
  const first = shown.current

  // After the words are drawn, remember how many there are.
  useEffect(() => {
    shown.current = box.current?.querySelectorAll('.tok').length ?? 0
  })

  const components: Components = {
    a: ({ href, children }) => (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    ),
    span: (props: ComponentPropsWithoutRef<'span'>) => {
      const { children, className } = props
      const data = props as Record<string, unknown>
      if (!String(className ?? '').includes('tok')) return <span className={className}>{children}</span>
      const at = Number(data['data-i'])
      const total = Number(data['data-n'])
      const fresh = at >= first
      const delay = fresh ? Math.min((at - first) * STAGGER_MS, STAGGER_CAP_MS) : 0
      const fromEnd = total - 1 - at
      return (
        <span
          className="tok"
          data-fresh={fresh ? '' : undefined}
          data-tail={live && fromEnd < TAIL ? fromEnd + 1 : undefined}
          style={fresh && delay ? { animationDelay: `calc(${delay}ms * var(--tm))` } : undefined}
        >
          {children}
        </span>
      )
    },
  }

  return (
    <div className="md" ref={box}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeWords]} components={components}>
        {text}
      </ReactMarkdown>
    </div>
  )
}
