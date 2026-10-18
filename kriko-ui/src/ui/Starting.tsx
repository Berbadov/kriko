import { useEffect, useState } from 'react'
import markSvg from '../assets/mark.svg?raw'

/** The logo files are white. They take the colour of the text instead. */
const ink = (svg: string) => svg.replaceAll('#ffffff', 'currentColor')

/** What the window shows while the engine comes up, so the first seconds are
 *  never an empty window. After a while it says the wait is longer than usual. */
export function Starting() {
  const [slow, setSlow] = useState(false)
  useEffect(() => {
    const timer = window.setTimeout(() => setSlow(true), 20000)
    return () => window.clearTimeout(timer)
  }, [])
  return (
    <div className="starting" role="status" aria-live="polite">
      <span className="starting-mark" dangerouslySetInnerHTML={{ __html: ink(markSvg) }} />
      <span className="starting-bar" aria-hidden="true" />
      <p>{slow ? 'Still starting. The first start after an install can take a little longer.' : 'Starting Kriko…'}</p>
    </div>
  )
}
