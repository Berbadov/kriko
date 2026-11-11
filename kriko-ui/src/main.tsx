import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { EngineProvider } from './engine/Engine'
import { Gate } from './Gate'
import { TitleBar } from './ui/TitleBar'
import { PrefsProvider } from './prefs'
import './styles/base.css'
import './arc/arc.css'
import './styles/shell.css'
import './styles/chat.css'
import './styles/activity.css'
import './styles/compare.css'
import './styles/estimate.css'
import './styles/panels.css'
import './styles/settings.css'
import './styles/logs.css'
import './styles/rail.css'
import './styles/tour.css'
import './styles/identity.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PrefsProvider>
      <EngineProvider>
        <TitleBar />
        <Gate />
      </EngineProvider>
    </PrefsProvider>
  </StrictMode>,
)
