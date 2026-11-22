import { useRef, useState, type DragEvent } from 'react'

/** Step one: the file. A drop zone with a button inside it, so the keyboard reaches it
 *  and a drag works too. The file is read in this window and goes nowhere else. */
export function ChooseFile({ name, detail, busy, problem, onFile }: {
  /** The chosen file's name, once one is read. */
  name: string
  /** What was found in it, said in words. */
  detail: string
  busy: boolean
  problem: string
  onFile: (file: File) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  const drop = (event: DragEvent) => {
    event.preventDefault()
    setOver(false)
    const dropped = event.dataTransfer.files[0]
    if (dropped) onFile(dropped)
  }

  return (
    <section className="k-group" aria-labelledby="checklist-step-file">
      <h2 className="k-caption" id="checklist-step-file">1. Choose a file</h2>
      <div
        className="k-card checklist-drop"
        data-over={over || undefined}
        data-pad
        onDragOver={(event) => { event.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={drop}
      >
        <div className="checklist-drop-text">
          {name ? (
            <>
              <strong className="checklist-file">{name}</strong>
              <span>{detail}</span>
            </>
          ) : (
            <>
              <strong>Drop a .csv or .xlsx file here</strong>
              <span>One product per row, with a column for its name.</span>
            </>
          )}
        </div>
        <button
          type="button"
          className="k-btn"
          data-kind={name ? undefined : 'primary'}
          disabled={busy}
          onClick={() => input.current?.click()}
        >
          {name ? 'Choose another file' : 'Choose a file'}
        </button>
        <input
          ref={input}
          type="file"
          hidden
          accept=".csv,.tsv,.txt,.xlsx,.xlsm,.xls,.ods"
          onChange={(event) => {
            const picked = event.target.files?.[0]
            if (picked) onFile(picked)
            event.target.value = ''
          }}
        />
      </div>
      <p className="checklist-note">Your file is read in this window and never uploaded; only the product names go to the engine on this computer.</p>
      <p className="checklist-status" role="status" aria-live="polite">{busy ? 'Reading the file…' : ''}</p>
      {problem && <p className="k-notice" data-tone="risk" role="alert">{problem}</p>}
    </section>
  )
}
