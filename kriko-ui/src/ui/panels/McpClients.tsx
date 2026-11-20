import { useState } from 'react'
import { clientState, useMcpClients, type McpClient } from '../../engine/mcpclients'
import { copyText } from '../clipboard'
import { Section, Setting, State } from './settingsParts'
import '../../styles/mcp.css'

/** Kriko inside a chat app that is not Kriko: one row per app, its state, and the
 *  word that connects it. The chosen app's own setup (the exact config, the file,
 *  the start command) is drawn under the list. */
export function McpClientsGroup() {
  const { doc, problem, writing, write } = useMcpClients()
  const [picked, setPicked] = useState('generic')
  const [copied, setCopied] = useState('')

  if (!doc) return problem ? <p className="error-note">{problem}</p> : null
  const client: McpClient = doc.clients.find((row) => row.id === picked) ?? doc.clients[0]

  const copy = async (what: string, text: string) => {
    setCopied((await copyText(text)) ? what : '')
    window.setTimeout(() => setCopied(''), 2000)
  }

  return (
    <>
      <Section
        title="Chat clients"
        note="Connect writes Kriko into the chat app's own settings file, so the app can look products up here. Lookups are free. A chat answer uses your agent."
      >
        {problem && <p className="error-note">{problem}</p>}
        {doc.clients.map((row) => {
          const pill = clientState(row.state)
          const busy = writing === row.id
          return (
            <Setting
              key={row.id}
              label={row.label}
              note={row.note}
              state={<State tone={pill.tone === 'none' ? undefined : pill.tone}>{pill.text}</State>}
              control={
                <>
                  {row.writable && row.state === 'connected' && (
                    <button type="button" className="k-btn" data-size="sm" disabled>
                      Connected
                    </button>
                  )}
                  {row.writable && row.state !== 'connected' && row.state !== 'unreadable' && (
                    <button type="button" className="k-btn" data-size="sm" disabled={busy} onClick={() => void write(row.id)}>
                      {busy ? 'Connecting…' : row.state === 'stale' ? 'Point it here' : 'Connect'}
                    </button>
                  )}
                  <button type="button" className="k-btn" data-size="sm" data-kind="quiet" aria-pressed={picked === row.id} onClick={() => setPicked(row.id)}>
                    {picked === row.id ? 'Showing setup' : 'Show setup'}
                  </button>
                </>
              }
            />
          )
        })}
      </Section>

      <Section title={`Setup for ${client.label}`}>
        {client.state === 'unreadable' && <p className="error-note">Kriko will not overwrite a file it cannot read. Fix it by hand, or paste the config below into it.</p>}
        {client.path && <Setting stack label="File" note="Where the config goes." control={<code className="settings-path">{client.path}</code>} />}
        {client.start && (
          <Setting
            stack
            label="Start command"
            note="Start Kriko's local server with this, then give the app the address in its config."
            control={
              <div className="settings-copy">
                <code>{client.start}</code>
                <button type="button" className="k-btn" data-size="sm" aria-label={copied === 'start' ? 'Copied' : 'Copy the start command'} onClick={() => void copy('start', client.start ?? '')}>
                  {copied === 'start' ? 'Copied' : 'Copy'}
                </button>
              </div>
            }
          />
        )}
        <Setting
          stack
          label="Config"
          note="Paste this into the app's config, or let Kriko write it with Connect."
          control={
            <>
              <pre className="mcp-snippet" tabIndex={0} aria-label={`${client.label} config`}>
                {client.snippet}
              </pre>
              <button type="button" className="k-btn" data-size="sm" onClick={() => void copy('snippet', client.snippet)}>
                {copied === 'snippet' ? 'Copied' : 'Copy the config'}
              </button>
            </>
          }
        />
      </Section>
    </>
  )
}
