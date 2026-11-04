/** A captured screen belongs to the queue before the assistant route leaves. */
export async function queueAssistantScan<T>(options: {
  signal: AbortSignal;
  read: () => Promise<T>;
  keep: () => Promise<string | undefined>;
  enqueue: (reading: T, imageUri: string | undefined) => void;
}): Promise<boolean> {
  if (options.signal.aborted) return false;
  const reading = await options.read();
  if (options.signal.aborted) return false;
  const image = await options.keep();
  if (options.signal.aborted) return false;
  options.enqueue(reading, image);
  return true;
}
