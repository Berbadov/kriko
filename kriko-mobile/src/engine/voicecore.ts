export type VoiceEvent = {
  sessionId: string;
  status: 'listening' | 'processing' | 'result' | 'error' | 'cancelled';
  text?: string;
  final?: boolean;
  code?: string;
};

/** Partial hypotheses replace one another; existing typed words are preserved. */
export function voiceDraft(base: string, transcript: string): string {
  const spoken = transcript.trim();
  if (!spoken) return base;
  return `${base.trimEnd()}${base.trim() ? ' ' : ''}${spoken}`.slice(0, 2000);
}

/** Late recognizer callbacks may never change a cancelled or newer draft. */
export class VoiceDraftSession {
  active = true;
  constructor(readonly id: string, readonly base: string) {}

  accept(event: VoiceEvent): { text?: string; terminal: boolean } | null {
    if (!this.active || event.sessionId !== this.id) return null;
    const terminal = event.status === 'error' || event.status === 'cancelled' ||
      (event.status === 'result' && event.final === true);
    if (terminal) this.active = false;
    return {
      ...(event.status === 'result' && typeof event.text === 'string'
        ? { text: voiceDraft(this.base, event.text) } : {}),
      terminal,
    };
  }

  cancel(): void { this.active = false; }
}
