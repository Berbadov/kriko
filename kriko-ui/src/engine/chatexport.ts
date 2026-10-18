import { get, seg, type ApiMessage } from './api'
import { demoThreads } from './threads'

/** A chat as Markdown: the title, then each question and the answer that came back,
 *  with the agent that wrote it. Live, the messages come from the engine. */

const rule = (text: string) => text.replace(/\r\n/g, '\n').trim()

export interface Said {
  role: 'reader' | 'agent'
  text: string
  agent?: string
}

export function markdownOf(title: string, said: Said[]): string {
  const out = [`# ${title || 'Chat'}`, '']
  for (const line of said) {
    out.push(line.role === 'reader' ? '## You' : `## ${line.agent || 'Agent'}`, '', rule(line.text), '')
  }
  return `${out.join('\n').trimEnd()}\n`
}

export async function chatMarkdown(id: string, title: string, live: boolean): Promise<string> {
  if (!live) {
    const found = demoThreads.get(id)
    const said: Said[] = (found?.turns ?? []).flatMap((turn) => [
      { role: 'reader' as const, text: turn.prompt },
      ...(turn.answer ? [{ role: 'agent' as const, text: turn.answer, agent: turn.agent?.label }] : []),
    ])
    return markdownOf(title, said)
  }
  const data = await get<{ items: ApiMessage[] }>(`/api/chat/threads/${seg(id)}/messages`)
  return markdownOf(
    title,
    data.items.map((m) => ({ role: m.role, text: m.text, agent: m.agent?.label || m.agent?.id })),
  )
}
