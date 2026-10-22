import { useCallback, useEffect, useRef, useState } from 'react'
import { get, post } from './api'
import { useEngine } from './Engine'

/** The config a chat client needs to reach this Kriko. Live, it is the engine's
 *  `/api/mcp-clients`; the engine builds each snippet, because only it knows
 *  which command starts it and which store it reads. In demo mode the same
 *  shapes are kept in the window. */

export type McpState = 'shown' | 'absent' | 'connected' | 'stale' | 'unreadable'

export interface McpClient {
  id: string
  label: string
  note: string
  /** The exact text to paste, in this client's own key. */
  snippet: string
  /** The client's config file, or empty where there is none to write. */
  path: string
  writable: boolean
  state: McpState
  detail?: string
  /** For a client that takes a URL: the command that serves it. */
  start?: string
}

export interface McpDoc {
  server_name: string
  store: string
  command: string
  frozen: boolean
  url: string
  clients: McpClient[]
}

const DEMO_SERVER = {
  type: 'stdio',
  command: '/Applications/Kriko.app/Contents/MacOS/kriko-sidecar',
  args: ['--mcp', '--store', '/Users/you/.kriko/knowledge.sqlite'],
}
const snippet = (key: string) => JSON.stringify({ [key]: { kriko: DEMO_SERVER } }, null, 2)

const DEMO_DOC: McpDoc = {
  server_name: 'kriko',
  store: '/Users/you/.kriko/knowledge.sqlite',
  command: DEMO_SERVER.command,
  frozen: true,
  url: 'http://127.0.0.1:8788/mcp',
  clients: [
    { id: 'generic', label: 'Any MCP client', note: "Add this to the client's MCP servers. Where it goes depends on the client.", snippet: snippet('mcpServers'), path: '', writable: false, state: 'shown' },
    { id: 'desktop', label: 'Desktop chat app', note: 'Claude Desktop reads this file at start-up; restart it after writing.', snippet: snippet('mcpServers'), path: '~/Library/Application Support/Claude/claude_desktop_config.json', writable: true, state: 'absent' },
    { id: 'ide', label: 'IDE chat', note: "Cursor's global MCP file. Restart the chat panel after writing.", snippet: snippet('mcpServers'), path: '~/.cursor/mcp.json', writable: true, state: 'absent' },
    { id: 'vscode', label: 'VS Code chat', note: "VS Code's user MCP file, which names its map `servers`.", snippet: snippet('servers'), path: '~/Library/Application Support/Code/User/mcp.json', writable: true, state: 'absent' },
    {
      id: 'url',
      label: 'A client that needs a URL',
      note: 'Start Kriko’s local server with the command below, then give the client this address. It answers on this machine only.',
      snippet: JSON.stringify({ mcpServers: { kriko: { url: 'http://127.0.0.1:8788/mcp' } } }, null, 2),
      path: '',
      writable: false,
      state: 'shown',
      start: '/Applications/Kriko.app/Contents/MacOS/kriko-sidecar --mcp --mcp-http --store /Users/you/.kriko/knowledge.sqlite',
    },
  ],
}

export function useMcpClients() {
  const { mode } = useEngine()
  const [doc, setDoc] = useState<McpDoc | null>(null)
  const [problem, setProblem] = useState('')
  const [writing, setWriting] = useState('')
  const demo = useRef<McpDoc>(structuredClone(DEMO_DOC))

  const load = useCallback(async () => {
    setProblem('')
    if (mode === 'checking') return
    if (mode !== 'live') {
      setDoc(structuredClone(demo.current))
      return
    }
    try {
      setDoc(await get<McpDoc>('/api/mcp-clients'))
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not read the chat client settings.')
    }
  }, [mode])

  useEffect(() => {
    void load()
  }, [load])

  /** Write Kriko into one client's config file, then read the listing again. */
  const write = useCallback(
    async (id: string) => {
      setWriting(id)
      setProblem('')
      try {
        if (mode !== 'live') {
          demo.current.clients = demo.current.clients.map((row) => (row.id === id ? { ...row, state: 'connected' } : row))
        } else {
          await post(`/api/mcp-clients/${encodeURIComponent(id)}/write`)
        }
        await load()
      } catch (error) {
        setProblem(error instanceof Error ? error.message : 'Could not write the config file.')
      } finally {
        setWriting('')
      }
    },
    [mode, load],
  )

  return { doc, problem, writing, write }
}
