export interface AuditStorage {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
}

/** Atomic read-modify-write transactions over an async string store. */
export function createAuditTransactions<T extends { id: string; status: string }>(
  storage: AuditStorage,
  key: string,
  limit: number,
) {
  let queue: Promise<void> = Promise.resolve();
  let epoch = 0;

  function serialize<R>(operation: () => Promise<R>): Promise<R> {
    const result = queue.then(operation);
    queue = result.then(() => undefined, () => undefined);
    return result;
  }

  async function read(): Promise<T[]> {
    const raw = await storage.getItem(key);
    try {
      const value: unknown = JSON.parse(raw || '[]');
      return Array.isArray(value) ? value as T[] : [];
    } catch { return []; }
  }

  return {
    load: () => serialize(read),
    begin(entry: T): Promise<number | null> {
      const requestedEpoch = epoch;
      return serialize(async () => {
        if (requestedEpoch !== epoch) return null;
        const entries = await read();
        if (requestedEpoch !== epoch) return null;
        entries.push(entry);
        await storage.setItem(key, JSON.stringify(entries.slice(-limit)));
        return requestedEpoch === epoch ? requestedEpoch : null;
      });
    },
    finish(id: string, patch: Partial<T>, requestedEpoch: number): Promise<boolean> {
      return serialize(async () => {
        if (requestedEpoch !== epoch) return false;
        const entries = await read();
        if (requestedEpoch !== epoch) return false;
        if (!entries.some((entry) => entry.id === id)) return false;
        const updated = entries.map((entry) => entry.id === id ? { ...entry, ...patch } : entry);
        await storage.setItem(key, JSON.stringify(updated.slice(-limit)));
        return requestedEpoch === epoch;
      });
    },
    clear(): Promise<T[]> {
      const requestedEpoch = ++epoch;
      return serialize(async () => {
        const entries = await read();
        if (requestedEpoch !== epoch) return [];
        await storage.setItem(key, '[]');
        return entries;
      });
    },
  };
}
