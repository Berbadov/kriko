import { useEffect, useRef, useState } from 'react'
import { useChat } from '../chat'
import { chatMarkdown } from '../engine/chatexport'
import { useThreads, type ChatThread } from '../engine/threads'
import { copyText } from './clipboard'
import { Icon } from './Icon'

/** The one row that is open, and what it is doing: showing its actions, being
 *  named, or asking before it deletes. Resting rows are not in the state. */
type Doing = { id: string; what: 'actions' | 'name' | 'delete' } | null

/** The most recent chats shown under Pinned. Pinned chats are never cut. */
const RECENT_MAX = 30

/** The chats the reader has had: pinned ones first, then the recent. A search box
 *  finds a chat by what was said in it. Each chat opens on the Ask screen, and
 *  its actions are words in a "More" disclosure. The block draws nothing when
 *  there are no chats and no search, so a fresh install shows no empty list. */
export function ChatsList({ onOpen }: { onOpen: (threadId: string) => void }) {
  const { threadId, newChat, open } = useChat()
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
  // Remember that there were chats, so a search that finds none does not take the block away.
  if (threads.length && !kept) setKept(true)

  if (!threads.length && !query && !kept) return null

  const say = (words: string) => {
    setNote(words)
    window.clearTimeout(noteTimer.current)
    noteTimer.current = window.setTimeout(() => setNote(''), 1800)
  }

  const openRow = (row: ChatThread) => {
    setDoing(null)
    void open(row.id)
    onOpen(row.id)
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
  const recent = threads.filter((row) => !row.pinned).slice(0, RECENT_MAX)

  const item = (row: ChatThread) => {
    const mine = doing?.id === row.id ? doing.what : null
    const current = row.id === threadId
    return (
      <li key={row.id} className="k-row chats-row" data-on={current} data-open={mine === 'actions' || undefined}>
        <span className="k-row-icon" aria-hidden="true">
          <Icon name={row.pinned ? 'pin' : 'chat'} size={16} />
        </span>
        {mine === 'name' ? (
          <input
            className="k-input chats-name"
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
        ) : (
          <button type="button" className="chats-open" onClick={() => openRow(row)} aria-current={current ? 'true' : undefined} title={`${row.title} · ${row.when}`}>
            <span className="k-row-main">
              <span className="k-row-title">{row.title}</span>
            </span>
          </button>
        )}
        {mine !== 'name' && <span className="k-row-value">{row.when}</span>}
        {mine !== 'name' && (
          <button
            type="button"
            className="k-btn"
            data-size="sm"
            data-kind="quiet"
            aria-expanded={mine === 'actions' || mine === 'delete'}
            aria-label={`More for ${row.title}`}
            onClick={() => setDoing(mine === 'actions' || mine === 'delete' ? null : { id: row.id, what: 'actions' })}
          >
            More
          </button>
        )}

        {mine === 'actions' && (
          <div className="chats-acts" role="group" aria-label={`Actions for ${row.title}`}>
            <button type="button" className="k-btn" data-size="sm" data-kind="quiet" aria-label={`Open ${row.title}`} onClick={() => openRow(row)}>
              Open
            </button>
            <button
              type="button"
              className="k-btn"
              data-size="sm"
              data-kind="quiet"
              aria-pressed={row.pinned}
              aria-label={row.pinned ? `Unpin ${row.title}` : `Pin ${row.title}`}
              onClick={() => {
                setDoing(null)
                void pin(row.id, !row.pinned)
              }}
            >
              {row.pinned ? 'Unpin' : 'Pin'}
            </button>
            <button
              type="button"
              className="k-btn"
              data-size="sm"
              data-kind="quiet"
              aria-label={`Rename ${row.title}`}
              onClick={() => {
                setTitle(row.title)
                setDoing({ id: row.id, what: 'name' })
              }}
            >
              Rename
            </button>
            <button type="button" className="k-btn" data-size="sm" data-kind="quiet" aria-label={`Copy ${row.title} as Markdown`} onClick={() => void copyChat(row)}>
              Copy as Markdown
            </button>
            <button type="button" className="k-btn" data-size="sm" data-kind="quiet" aria-label={`Delete ${row.title}`} onClick={() => setDoing({ id: row.id, what: 'delete' })}>
              Delete
            </button>
          </div>
        )}

        {mine === 'delete' && (
          <div className="chats-acts chats-ask" role="group" aria-label={`Delete ${row.title}?`}>
            <span>Delete this chat?</span>
            <button
              type="button"
              className="k-btn"
              data-size="sm"
              data-kind="danger"
              onClick={() => {
                setDoing(null)
                if (current) newChat()
                void remove(row.id)
              }}
            >
              Delete
            </button>
            <button type="button" className="k-btn" data-size="sm" data-kind="quiet" onClick={() => setDoing(null)}>
              Keep
            </button>
          </div>
        )}
      </li>
    )
  }

  return (
    <section className="k-group chats" aria-label="Chats">
      <h2 className="k-caption">Chats</h2>
      <div className="chats-find">
        <input type="search" className="k-input" value={typed} onChange={(event) => setTyped(event.target.value)} placeholder="Search your chats" aria-label="Search your chats" />
        {typed && (
          <button type="button" className="k-btn" data-size="sm" data-kind="quiet" aria-label="Clear the search" onClick={() => setTyped('')}>
            Clear
          </button>
        )}
      </div>
      {(problem || note) && (
        <p className="chats-note" role="status">
          {problem || note}
        </p>
      )}
      {pinned.length > 0 && (
        <section className="chats-group" aria-label="Pinned">
          <h3 className="k-caption">Pinned</h3>
          <div className="k-card">
            <ul className="k-list">{pinned.map(item)}</ul>
          </div>
        </section>
      )}
      {recent.length > 0 && (
        <section className="chats-group" aria-label="Recent">
          <h3 className="k-caption">Recent</h3>
          <div className="k-card">
            <ul className="k-list">{recent.map(item)}</ul>
          </div>
        </section>
      )}
      {!threads.length && <p className="chats-empty">No chat has those words.</p>}
    </section>
  )
}
