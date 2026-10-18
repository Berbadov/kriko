import App from './App'
import { UpdateProvider } from './engine/appupdate'
import { useEngine } from './engine/Engine'
import { Starting } from './ui/Starting'
import { UpdateNotice } from './ui/UpdateNotice'

/** Nothing that reads the engine is drawn until it has answered or been given up on. */
export function Gate() {
  const { mode } = useEngine()
  if (mode === 'checking') return <Starting />
  return (
    <UpdateProvider>
      <App />
      <UpdateNotice />
    </UpdateProvider>
  )
}
