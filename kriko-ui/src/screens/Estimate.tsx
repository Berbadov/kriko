import { useState } from 'react'
import { useEngine } from '../engine/Engine'
import { deleteEstimate, useEstimates, type Estimate } from '../engine/estimates'
import { PROCUREMENT_CHANGED_EVENT } from '../engine/procurement'
import { showDrawer } from '../ui/drawerEvents'
import { EstimateList } from './procurement/EstimateList'
import { EstimateEditor } from './procurement/EstimateEditor'
import { ProcurementOverview } from './procurement/Overview'

/** The Procurement desk (screen id `estimate`): what the saved estimates are
 *  worth and what needs the eye, the list of estimates, and the one open for
 *  editing below it. The arithmetic lives in the engine modules; this screen
 *  only draws it.
 *
 *  `target` is the open editor: '' for a new estimate, an id for a saved one,
 *  null when no estimate is open.
 */

const notify = () => window.dispatchEvent(new Event(PROCUREMENT_CHANGED_EVENT))

export function EstimateScreen() {
  const { mode } = useEngine()
  const saved = useEstimates()
  const [target, setTarget] = useState<string | null>(null)
  // Bumped only when an estimate is opened or started, so saving keeps the editor mounted.
  const [session, setSession] = useState(0)
  const [problem, setProblem] = useState('')

  const open = (estimateId: string) => {
    setTarget(estimateId)
    setSession((current) => current + 1)
  }

  if (mode !== 'live') {
    return (
      <section className="k-screen" data-width="wide">
        <header className="k-head">
          <h1 className="k-title">Procurement</h1>
        </header>
        <div className="k-empty">
          <strong>Procurement needs the engine</strong>
          <p>Connect Kriko&rsquo;s engine to compare vendor quotes, see landed costs and keep estimates.</p>
          <button type="button" className="k-btn" data-kind="primary" onClick={() => showDrawer('setup')}>
            Open Settings
          </button>
        </div>
      </section>
    )
  }

  const onSaved = (estimate: Estimate) => {
    setTarget(estimate.estimate_id)
    void saved.reload()
    notify()
  }

  /** The editor has deleted its estimate; the list and the overview follow. */
  const onDeleted = (estimateId: string) => {
    if (target === estimateId) setTarget(null)
    void saved.reload()
    notify()
  }

  const removeFromList = async (estimateId: string) => {
    try {
      await deleteEstimate(estimateId)
    } catch (error) {
      setProblem(error instanceof Error ? error.message : 'Could not delete the estimate.')
      return
    }
    onDeleted(estimateId)
  }

  return (
    <section className="k-screen" data-width="wide">
      <header className="k-head">
        <h1 className="k-title">Procurement</h1>
      </header>

      <ProcurementOverview onOpen={open} />

      <EstimateList
        items={saved.items}
        problem={problem || saved.problem}
        activeId={target ?? ''}
        onOpen={open}
        onDelete={(estimateId) => void removeFromList(estimateId)}
        onNew={() => { setTarget(''); setSession((current) => current + 1) }}
      />

      {target !== null && (
        <EstimateEditor
          key={session}
          target={target}
          onSaved={onSaved}
          onDeleted={onDeleted}
          onClose={() => setTarget(null)}
        />
      )}
    </section>
  )
}
