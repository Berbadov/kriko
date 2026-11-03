import { useState } from 'react'
import { useMcpClients, type McpClient, type McpState } from '../../engine/mcpclients'
import { copyText } from '../clipboard'
import { Select } from '../controls'
import '../../styles/mcp.css'

const STATE_WORDS: Record<McpState, string> = {
  shown: '',
  absent: 'Not added yet',
  connected: 'Added',
  stale: 'Added, but it points at a different Kriko store',
  unreadable: 'Its config file cannot be read',
}

/** Kriko inside a chat app that is not Kriko: the exact config for it, to copy
 *  or to write. One entry point for Settings, so the picker around it can change
 *  without touching this. */
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
    <section className="panel-group mcp">
      <h3>Use Kriko in another chat</h3>
      {problem && <p className="error-note">{problem}</p>}
      <div className="setting">
        <span>Chat client</span>
        <Select label="Chat client" value={client.id} options={doc.clients.map((row) => ({ value: row.id, label: row.label }))} onChange={setPicked} />
      </div>
      {STATE_WORDS[client.state] && (
        <div className="setting">
          <span>Status</span>
          <span className="state" data-tone={client.state === 'connected' ? 'ok' : client.state === 'unreadable' ? 'risk' : 'warn'}>
            {STATE_WORDS[client.state]}
            {client.detail ? `: ${client.detail}` : ''}
          </span>
        </div>
      )}
      {client.start && (
        <div className="command">
          <code>{client.start}</code>
          <button onClick={() => void copy('start', client.start ?? '')}>{copied === 'start' ? 'Copied' : 'Copy'}</button>
        </div>
      )}
      <pre className="mcp-snippet" tabIndex={0} aria-label={`${client.label} config`}>
        {client.snippet}
      </pre>
      <div className="setting actions">
        <button className="btn" onClick={() => void copy('snippet', client.snippet)}>
          {copied === 'snippet' ? 'Copied' : 'Copy config'}
        </button>
        {client.writable && (
          <button className="btn primary" onClick={() => void write(client.id)} disabled={writing === client.id || client.state === 'connected'}>
            {writing === client.id ? 'Writing…' : client.state === 'connected' ? 'Already added' : 'Add it for me'}
          </button>
        )}
      </div>
      {client.path && (
        <div className="setting">
          <span>Config file</span>
          <span className="value path">{client.path}</span>
        </div>
      )}
      {client.state === 'unreadable' && <p className="error-note">Fix that file by hand, or paste the config above into it. Kriko will not overwrite a file it cannot read.</p>}
      <p className="panel-note" data-kind="data">Lookups are free. A chat answer uses your agent.</p>
      {client.note && (
        <details className="disclosure">
          <summary>How to add it</summary>
          <p className="panel-note">{client.note}</p>
        </details>
      )}
    </section>
  )
}
