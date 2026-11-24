import { useCallback, useRef, useState } from 'react'

/** The most checks one comparison holds. */
export const MAX_SLOTS = 4

interface BoardOptions {
  /** Called with the whole board after the reader changes it, never on reload. */
  onChange?: (lookupIds: string[]) => void
}

/** The Compare board.
 *
 *  `add` and `remove` read the current ids through a ref instead of the render
 *  they were created in: a research that finishes after another column was
 *  added must append to what is there now, never to the board it started from.
 *  `place` is the engine's board replacing this one. */
export function useBoard({ onChange }: BoardOptions = {}) {
  const [slots, setSlots] = useState<string[]>([])
  const current = useRef(slots)

  const put = useCallback((ids: string[]) => {
    current.current = ids
    setSlots(ids)
  }, [])

  const add = useCallback(
    (lookupId: string) => {
      const ids = current.current
      if (!lookupId || ids.includes(lookupId)) return true
      if (ids.length >= MAX_SLOTS) return false
      const next = [...ids, lookupId]
      put(next)
      onChange?.(next)
      return true
    },
    [onChange, put],
  )

  const remove = useCallback(
    (lookupId: string) => {
      const ids = current.current
      if (!ids.includes(lookupId)) return
      const next = ids.filter((id) => id !== lookupId)
      put(next)
      onChange?.(next)
    },
    [onChange, put],
  )

  const place = useCallback(
    (ids: string[]) => {
      put(ids.slice(0, MAX_SLOTS))
    },
    [put],
  )

  /** The ids as they are right now, for a caller that only has this render's closure. */
  const read = useCallback(() => current.current, [])

  return { slots, add, remove, place, read }
}
