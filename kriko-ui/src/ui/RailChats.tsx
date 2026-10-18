import { useState } from 'react'
import { useChat } from '../chat'
import { useThreads } from '../engine/threads'
import { Icon } from './Icon'

/** The chats the reader has had. The rail shows the latest few, and the list scrolls. */
export function RailChats({ onOpen }: { onOpen: (threadId: string) => void }) {
  const { threadId, newChat } = useChat()
  const { threads, problem, remove } = useThreads()
  const [asking, setAsking] = useState<string | null>(null)

  if (!threads.length) return null

  return (
    <section className="rail-chats" aria-label="Recent chats">
      <h2>Recent chats</h2>
      {problem && <p className="rail-chats-note">{problem}</p>}
      <ul>
        {threads.slice(0, 30).map((row) => (
          <li key={row.id} className="rail-chat" data-on={row.id === threadId} data-asking={asking === row.id}>
            {asking === row.id ? (
              <span className="rail-chat-ask">
                <span>Delete?</span>
                <button
                  onClick={() => {
                    setAsking(null)
                    if (row.id === threadId) newChat()
                    void remove(row.id)
                  }}
                >
                  Delete
                </button>
                <button onClick={() => setAsking(null)}>Keep</button>
              </span>
            ) : (
              <>
                <button className="rail-chat-main" onClick={() => onOpen(row.id)} title={`${row.title} · ${row.when}`} aria-current={row.id === threadId ? 'true' : undefined}>
                  {row.title}
                </button>
                <button className="icon-btn sm rail-chat-del" onClick={() => setAsking(row.id)} aria-label={`Delete ${row.title}`} title="Delete">
                  <Icon name="x" size={14} />
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
