/** The agent's orb: a small blue sphere that breathes while the agent is idle
 *  and pulses harder while it works. Pure CSS — still when motion is off. */
export function Orb({ size = 9, busy = false }: { size?: number; busy?: boolean }) {
  return (
    <span
      className="orb"
      data-on={busy ? 'true' : undefined}
      aria-hidden="true"
      style={size !== 9 ? { width: size, height: size } : undefined}
    />
  )
}
