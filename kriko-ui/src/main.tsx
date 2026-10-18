import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { EngineProvider } from './engine/Engine'
import { PrefsProvider } from './prefs'
import './styles/base.css'
import './styles/shell.css'
import './styles/chat.css'
import './styles/activity.css'
import './styles/compare.css'
import './styles/panels.css'
import './styles/tour.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PrefsProvider>
      <EngineProvider>
        <App />
      </EngineProvider>
    </PrefsProvider>
  </StrictMode>,
)
