import { useEffect, useState } from 'react'

/** What a screen shows while its chunk arrives: quiet rows where the content will
 *  be. It appears only if the wait passes 120 ms, so a chunk that is already
 *  warm (the usual case after the idle prefetch) never flashes anything. */
export function PageSkeleton() {
  const [late, setLate] = useState(false)
  useEffect(() => {
    const timer = window.setTimeout(() => setLate(true), 120)
    return () => window.clearTimeout(timer)
  }, [])
  if (!late) return null
  return (
    <section className="k-screen page-skeleton" role="status" aria-busy="true" aria-label="Loading">
      <div className="page-skeleton-title" />
      <div className="page-skeleton-card">
        {[0, 1, 2, 3].map((row) => (
          <div key={row} className="page-skeleton-row" />
        ))}
      </div>
    </section>
  )
}
