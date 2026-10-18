import { useEffect, useRef, useState } from 'react'
import { useChat } from '../chat'
import { chatMarkdown } from '../engine/chatexport'
import { useThreads, type ChatThread } from '../engine/threads'
import { copyText } from './clipboard'
import { Icon } from './Icon'

/** What the row is doing: resting, showing its actions, being named, or asking before it deletes. */
type Doing = { id: string; what: 'actions' | 'name' | 'delete' } | null

/** The chats the reader has had. Pinned ones lead. A box above finds a chat by what was said in it. */
export function RailChats({ onOpen }: { onOpen: (threadId: string) => void }) {
  const { threadId, newChat } = useChat()
  const [typed, setTyped] = useState('')
  const [query, setQuery] = useState('')
  const { threads, problem, remove, rename, pin, live } = useThreads(query)
  const [doing, setDoing] = useState<Doing>(null)
  const [note, setNote] = useState('')
  const [title, setTitle] = useState('')
  const [kept, setKept] = useState(false)
  const noteTimer = useRef(0)

  // The words are sent when the reader pauses, not on every key.
  useEffect(() => {
    const id = window.setTimeout(() => setQuery(typed), 220)
    return () => window.clearTimeout(id)
  }, [typed])
  useEffect(() => () => window.clearTimeout(noteTimer.current), [])
  // Remember that there were chats, so a search that finds none does not take the box away.
  useEffect(() => {
    if (threads.length) setKept(true)
  }, [threads.length])

  if (!threads.length && !query && !kept) return null

  const say = (words: string) => {
    setNote(words)
    window.clearTimeout(noteTimer.current)
    noteTimer.current = window.setTimeout(() => setNote(''), 1800)
  }

  const copyChat = async (row: ChatThread) => {
    setDoing(null)
    try {
      say((await copyText(await chatMarkdown(row.id, row.title, live))) ? 'Copied as Markdown' : 'Could not copy')
    } catch {
      say('Could not copy')
    }
  }

  const finishName = (row: ChatThread, keep: boolean) => {
    setDoing(null)
    if (keep && title.trim() && title.trim() !== row.title) void rename(row.id, title)
  }

  const pinned = threads.filter((row) => row.pinned)
  const recent = threads.filter((row) => !row.pinned).slice(0, 30)

  const item = (row: ChatThread) => {
    const mine = doing?.id === row.id ? doing.what : null
    return (
      <li key={row.id} className="rail-chat" data-on={row.id === threadId} data-asking={mine === 'delete'} data-open={mine === 'actions'}>
        {mine === 'delete' ? (
          <span className="rail-chat-ask">
            <span>Delete?</span>
            <button
              onClick={() => {
                setDoing(null)
                if (row.id === threadId) newChat()
                void remove(row.id)
              }}
            >
              Delete
            </button>
            <button onClick={() => setDoing(null)}>Keep</button>
          </span>
        ) : mine === 'name' ? (
          <input
            className="rail-chat-name"
            value={title}
            maxLength={60}
            autoFocus
            aria-label="Name of the chat"
            onChange={(event) => setTitle(event.target.value)}
            onFocus={(event) => event.target.select()}
            onBlur={() => finishName(row, true)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') finishName(row, true)
              else if (event.key === 'Escape') finishName(row, false)
            }}
          />
        ) : mine === 'actions' ? (
          <span className="rail-chat-acts">
            <button
              className="icon-btn sm"
              title="Rename"
              aria-label={`Rename ${row.title}`}
              onClick={() => {
                setTitle(row.title)
                setDoing({ id: row.id, what: 'name' })
              }}
            >
              <Icon name="rename" size={15} />
            </button>
            <button
              className="icon-btn sm"
              data-on={row.pinned}
              title={row.pinned ? 'Unpin' : 'Pin to the top'}
              aria-label={row.pinned ? `Unpin ${row.title}` : `Pin ${row.title}`}
              onClick={() => {
                setDoing(null)
                void pin(row.id, !row.pinned)
              }}
            >
              <Icon name="pin" size={15} />
            </button>
            <button className="icon-btn sm" title="Copy as Markdown" aria-label={`Copy ${row.title} as Markdown`} onClick={() => void copyChat(row)}>
              <Icon name="copy" size={15} />
            </button>
            <button className="icon-btn sm" title="Delete" aria-label={`Delete ${row.title}`} onClick={() => setDoing({ id: row.id, what: 'delete' })}>
              <Icon name="trash" size={15} />
            </button>
            <button className="icon-btn sm" title="Close" aria-label="Close" onClick={() => setDoing(null)}>
              <Icon name="x" size={14} />
            </button>
          </span>
        ) : (
          <>
            <button
              className="rail-chat-main"
              onClick={() => onOpen(row.id)}
              onDoubleClick={() => {
                setTitle(row.title)
                setDoing({ id: row.id, what: 'name' })
              }}
              title={`${row.title} · ${row.when}`}
              aria-current={row.id === threadId ? 'true' : undefined}
            >
              {row.pinned && <Icon name="pin" size={12} />}
              <span>{row.title}</span>
            </button>
            <button className="icon-btn sm rail-chat-del" onClick={() => setDoing({ id: row.id, what: 'actions' })} aria-label={`Actions for ${row.title}`} title="More">
              <Icon name="dots" size={15} />
            </button>
          </>
        )}
      </li>
    )
  }

  return (
    <section className="rail-chats" aria-label="Chats">
      <label className="rail-search">
        <Icon name="search" size={14} />
        <input value={typed} onChange={(event) => setTyped(event.target.value)} placeholder="Search chats" aria-label="Search chats" />
        {typed && (
          <button type="button" className="icon-btn sm" aria-label="Clear the search" onClick={() => setTyped('')}>
            <Icon name="x" size={13} />
          </button>
        )}
      </label>
      {(problem || note) && <p className="rail-chats-note">{problem || note}</p>}
      <div className="rail-chats-scroll">
        {pinned.length > 0 && (
          <>
            <h2>Pinned</h2>
            <ul>{pinned.map(item)}</ul>
          </>
        )}
        {recent.length > 0 && (
          <>
            <h2>{query ? 'Found' : 'Recent chats'}</h2>
            <ul>{recent.map(item)}</ul>
          </>
        )}
        {!threads.length && <p className="rail-chats-empty">No chat has those words.</p>}
      </div>
    </section>
  )
}
