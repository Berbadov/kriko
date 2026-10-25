import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import type { Question } from './src/activity/run'
import { PrefsProvider } from './src/prefs'
import { AskCard } from './src/screens/Chat'
import './src/styles/base.css'
import './src/styles/shell.css'
import './src/styles/chat.css'
import './src/styles/activity.css'

const question: Question = {
  id: 'q1',
  ask: 'Is your 2020 Renault Megane 4 a pre-facelift or facelift model?',
  options: ['Pre-facelift (2016–2019)', 'Facelift (2020)'],
  why: 'Oil specifications and change intervals differ between pre-facelift and facelift variants for the 1.5 Blue dCi engine.',
}
const agent = { id: '', label: 'Kriko Agent' }

function Page() {
  return (
    <main style={{ width: 840, margin: '0 auto', padding: '28px 20px', display: 'grid', gap: 28 }}>
      <section style={{ display: 'grid', gap: 10 }}>
        <small className="mono muted">ASKED, WAITING FOR AN ANSWER</small>
        <AskCard question={question} agent={agent} busy={false} onAnswer={() => undefined} onOwn={() => undefined} />
      </section>
      <section style={{ display: 'grid', gap: 10 }}>
        <small className="mono muted">ANSWERED, FOLDED</small>
        <AskCard question={question} agent={agent} busy onAnswer={() => undefined} onOwn={() => undefined} />
      </section>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PrefsProvider>
      <Page />
    </PrefsProvider>
  </StrictMode>,
)
