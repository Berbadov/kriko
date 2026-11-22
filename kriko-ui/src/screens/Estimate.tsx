import { takePendingOpen } from '../engine/pendingOpen'
import { useEffect, useState } from 'react'
import { useEngine } from '../engine/Engine'
import { deleteEstimate, useEstimates, type Estimate } from '../engine/estimates'
import { PROCUREMENT_CHANGED_EVENT } from '../engine/procurement'
import { showDrawer } from '../ui/drawerEvents'
import { EstimateList } from './procurement/EstimateList'
import { EstimateEditor } from './procurement/EstimateEditor'
import { ProcurementOverview } from './procurement/Overview'
import { VendorScorecard } from './procurement/Vendors'

/** The Procurement desk (screen id `estimate`): what the saved estimates are
 *  worth and what needs the eye, the list of estimates, and the one open for
 *  editing below it. The arithmetic lives in the engine modules; this screen
 *  only draws it.
 *
 *  `target` is the open editor: '' for a new estimate, an id for a saved one,
 *  null when no estimate is open.
 */

const notify = () => window.dispatchEvent(new Event(PROCUREMENT_CHANGED_EVENT))

/** The two views of the desk. The choice is remembered for this machine only. */
type Tab = 'estimates' | 'vendors'
const TAB_KEY = 'kriko.procurementTab'

const readTab = (): Tab => {
  try {
    return localStorage.getItem(TAB_KEY) === 'vendors' ? 'vendors' : 'estimates'
  } catch {
    return 'estimates'
  }
}

const saveTab = (tab: Tab) => {
  try {
    localStorage.setItem(TAB_KEY, tab)
  } catch {
    // A private window or blocked storage: the choice just is not remembered.
  }
}

export function EstimateScreen() {
  const { mode } = useEngine()
  const saved = useEstimates()
  const [target, setTarget] = useState<string | null>(null)
  // Bumped only when an estimate is opened or started, so saving keeps the editor mounted.
  const [session, setSession] = useState(0)
  const [problem, setProblem] = useState('')
  const [tab, setTab] = useState<Tab>(readTab)

  const open = (estimateId: string) => {
    setTarget(estimateId)
    setSession((current) => current + 1)
  }

  const choose = (next: Tab) => {
    setTab(next)
    saveTab(next)
  }

  // A request made before this screen was there (the palette, a link): take it once.
  useEffect(() => {
    const asked = takePendingOpen()
    if (asked.estimateId) {
      setTab('estimates')
      setTarget(asked.estimateId)
      setSession((current) => current + 1)
    } else if (asked.newEstimate) {
      setTab('estimates')
      setTarget('')
      setSession((current) => current + 1)
    }
  }, [])

  // A new estimate asked for while this screen is open.
  useEffect(() => {
    const created = () => {
      setTab('estimates')
      setTarget('')
      setSession((current) => current + 1)
    }
    window.addEventListener('kriko:new-estimate', created)
    return () => window.removeEventListener('kriko:new-estimate', created)
  }, [])

  // The Vendors view asks for an estimate to be opened in the editor.
  useEffect(() => {
    const opened = (event: Event) => {
      const estimateId = (event as CustomEvent<{ estimateId?: string }>).detail?.estimateId
      if (!estimateId) return
      setTab('estimates')
      saveTab('estimates')
      setTarget(estimateId)
      setSession((current) => current + 1)
    }
    window.addEventListener('kriko:open-estimate', opened)
    return () => window.removeEventListener('kriko:open-estimate', opened)
  }, [])

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

      <div className="k-seg vendors-tabs" role="tablist" aria-label="Procurement view">
        <button
          type="button"
          role="tab"
          id="procurement-tab-estimates"
          aria-selected={tab === 'estimates'}
          aria-controls="procurement-panel-estimates"
          onClick={() => choose('estimates')}
        >
          Estimates
        </button>
        <button
          type="button"
          role="tab"
          id="procurement-tab-vendors"
          aria-selected={tab === 'vendors'}
          aria-controls="procurement-panel-vendors"
          onClick={() => choose('vendors')}
        >
          Vendors
        </button>
      </div>

      <div role="tabpanel" id="procurement-panel-estimates" aria-labelledby="procurement-tab-estimates" hidden={tab !== 'estimates'}>
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
      </div>

      <div role="tabpanel" id="procurement-panel-vendors" aria-labelledby="procurement-tab-vendors" hidden={tab !== 'vendors'}>
        {tab === 'vendors' && <VendorScorecard />}
      </div>
    </section>
  )
}
