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
      <p className="panel-note">
        Add Kriko to a chat app or an editor and ask it about a product there. It answers with its sources and quotes. Lookups are free; a chat answer uses your agent.
      </p>
      {problem && <p className="error-note">{problem}</p>}
      <div className="setting">
        <span>Chat client</span>
        <Select label="Chat client" value={client.id} options={doc.clients.map((row) => ({ value: row.id, label: row.label }))} onChange={setPicked} />
      </div>
      <p className="panel-note">{client.note}</p>
      {client.start && (
        <div className="command">
          <code>{client.start}</code>
          <button onClick={() => void copy('start', client.start ?? '')}>{copied === 'start' ? 'Copied' : 'Copy'}</button>
        </div>
      )}
      <pre className="mcp-snippet" tabIndex={0} aria-label={`${client.label} config`}>
        {client.snippet}
      </pre>
      <div className="mcp-actions">
        <button className="btn" onClick={() => void copy('snippet', client.snippet)}>
          {copied === 'snippet' ? 'Copied' : 'Copy config'}
        </button>
        {client.writable && (
          <button className="btn primary" onClick={() => void write(client.id)} disabled={writing === client.id || client.state === 'connected'}>
            {writing === client.id ? 'Writing…' : client.state === 'connected' ? 'Already added' : 'Add it for me'}
          </button>
        )}
      </div>
      {client.path && <small className="panel-path">{client.path}</small>}
      {STATE_WORDS[client.state] && (
        <p className="panel-note mcp-state" data-ok={client.state === 'connected'} data-state={client.state}>
          {STATE_WORDS[client.state]}
          {client.detail ? `: ${client.detail}` : ''}
        </p>
      )}
      {client.state === 'unreadable' && <p className="error-note">Fix that file by hand, or paste the config above into it. Kriko will not overwrite a file it cannot read.</p>}
    </section>
  )
}
