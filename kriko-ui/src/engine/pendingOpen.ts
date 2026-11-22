/**
 * A request to open something on a screen that is not mounted yet.
 *
 * Screens are separate chunks, so when the palette says "open this estimate" the
 * Procurement screen may not exist for another few frames and would miss the
 * event. The shell records the request here the moment it is made; the screen
 * takes it once when it mounts. A screen that is already open hears the event
 * itself and never reads this.
 */
export interface PendingOpen {
  estimateId: string | null
  newEstimate: boolean
}

const pending: PendingOpen = { estimateId: null, newEstimate: false }

export function rememberEstimate(estimateId: string) {
  pending.estimateId = estimateId
  pending.newEstimate = false
}

export function rememberNewEstimate() {
  pending.estimateId = null
  pending.newEstimate = true
}

/** The request made while the screen was not there, once. */
export function takePendingOpen(): PendingOpen {
  const taken = { ...pending }
  pending.estimateId = null
  pending.newEstimate = false
  return taken
}
