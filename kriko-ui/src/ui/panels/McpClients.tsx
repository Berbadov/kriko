import { useState } from 'react'
import { useMcpClients, type McpClient, type McpState } from '../../engine/mcpclients'
import { copyText } from '../clipboard'
import { Select } from '../controls'
import { Icon } from '../Icon'
import { Group, Hint, IconButton, Row, State } from './settingsParts'
import '../../styles/mcp.css'

const STATE_WORDS: Record<McpState, string> = {
  shown: '',
  absent: 'Not added yet',
  connected: 'Added',
  stale: 'Added, but it points at a different Kriko store',
  unreadable: 'Its config file cannot be read',
}

/** The same states in a word or two, for the pill beside the name. */
const STATE_SHORT: Record<McpState, string> = {
  shown: '',
  absent: 'Not added',
  connected: 'Added',
  stale: 'Other store',
  unreadable: 'Unreadable',
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
    <Group
      icon="plug"
      title="Chat apps"
      hint={
        <Hint icon="coins" title="Cost">
          Lookups are free. A chat answer uses your agent.
        </Hint>
      }
    >
      {problem && <p className="error-note">{problem}</p>}
      <Row
        icon="chat"
        label="App"
        state={
          STATE_WORDS[client.state] ? (
            <State tone={client.state === 'connected' ? 'ok' : client.state === 'unreadable' ? 'risk' : 'warn'} icon={client.state === 'connected' ? 'check' : 'alert'}>
              {STATE_SHORT[client.state]}
            </State>
          ) : undefined
        }
      >
        <Select label="Chat client" value={client.id} options={doc.clients.map((row) => ({ value: row.id, label: row.label }))} onChange={setPicked} />
      </Row>
      {STATE_WORDS[client.state] && client.detail && <p className="panel-note" data-kind="warn">{STATE_WORDS[client.state]}: {client.detail}</p>}
      {client.start && (
        <div className="command">
          <code>{client.start}</code>
          <IconButton icon="copy" label={copied === 'start' ? 'Copied' : 'Copy the start command'} onClick={() => void copy('start', client.start ?? '')} />
        </div>
      )}
      <pre className="mcp-snippet" tabIndex={0} aria-label={`${client.label} config`}>
        {client.snippet}
      </pre>
      <Row actions>
        <button className="btn" onClick={() => void copy('snippet', client.snippet)}>
          <Icon name={copied === 'snippet' ? 'check' : 'copy'} size={18} />
          {copied === 'snippet' ? 'Copied' : 'Copy'}
        </button>
        {client.writable && (
          <button className="btn primary" onClick={() => void write(client.id)} disabled={writing === client.id || client.state === 'connected'}>
            <Icon name={client.state === 'connected' ? 'check' : 'plus'} size={18} />
            {writing === client.id ? 'Writing…' : client.state === 'connected' ? 'Added' : 'Add it'}
          </button>
        )}
      </Row>
      {client.path && (
        <Row icon="folder" label="File">
          <span className="value path">{client.path}</span>
        </Row>
      )}
      {client.state === 'unreadable' && <p className="error-note">Fix that file by hand, or paste the config above into it. Kriko will not overwrite a file it cannot read.</p>}
      {client.note && (
        <details className="disclosure">
          <summary>
            <span className="row-label">
              <span className="row-icon" aria-hidden="true">
                <Icon name="info" size={20} />
              </span>
              <span className="row-name">How to add it</span>
            </span>
          </summary>
          <p className="panel-note">{client.note}</p>
        </details>
      )}
    </Group>
  )
}
