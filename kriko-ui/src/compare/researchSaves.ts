/** Board edits stay local while research runs. Only a succeeded job whose
 * replacement is present in the durable draft may rewrite queued saves. */
export class ResearchSaves {
  private pending = new Set<Promise<void>>()
  private replacements = new Map<string, string>()

  begin(): () => void {
    let release!: () => void
    const pending = new Promise<void>((resolve) => { release = resolve })
    this.pending.add(pending)
    return () => { this.pending.delete(pending); release() }
  }

  confirm(source: string, job: string, state: string, durableIds: string[]): void {
    if (state === 'succeeded' && durableIds.includes(job)) this.replacements.set(source, job)
  }

  forget(id: string): void { this.replacements.delete(id) }

  async prepare(ids: string[]): Promise<string[]> {
    while (this.pending.size) await Promise.all([...this.pending])
    return [...new Set(ids.map((id) => {
      const seen = new Set<string>()
      while (this.replacements.has(id) && !seen.has(id)) {
        seen.add(id)
        id = this.replacements.get(id)!
      }
      return id
    }))]
  }
}
