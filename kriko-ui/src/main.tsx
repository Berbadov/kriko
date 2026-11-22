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
import './styles/system.css'
import './styles/checklist.css'
import './styles/settings-local.css'
import './styles/approval.css'
import './styles/agentmenu.css'
import './styles/vendors.css'
import './styles/palette.css'
import './styles/settings-data.css'
import './styles/settings-keys.css'
import './styles/settings-research.css'
import './styles/prices.css'
import './styles/product.css'
import './styles/library.css'
import './styles/work.css'
import './styles/procurement.css'
import './styles/perf.css'

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
