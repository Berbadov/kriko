import AsyncStorage from '@react-native-async-storage/async-storage';

import {
  normalizeShortlist,
  removeShortlistItem,
  upsertShortlistItem,
  type ShortlistInput,
  type ShortlistItem,
} from './shortlistCore';

export type { ShortlistInput, ShortlistItem } from './shortlistCore';
export {
  DEFAULT_WEIGHTS,
  WEIGHT_LEVELS,
  currentPrice,
  foldText,
  isValidShortlistItem,
  matchWatch,
  normalizeShortlist,
  priceDropStatus,
  rankShortlist,
  removeShortlistItem,
  upsertShortlistItem,
  type DecisionWeights,
  type DropStatus,
  type RankedItem,
  type RankReason,
  type WeightLevel,
} from './shortlistCore';

const STORAGE_KEY = '@kriko/shortlist-v1';

export async function loadShortlist(): Promise<ShortlistItem[]> {
  try {
    return normalizeShortlist(JSON.parse(await AsyncStorage.getItem(STORAGE_KEY) || '[]'));
  } catch { return []; }
}

async function save(items: ShortlistItem[]): Promise<void> {
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

/** Serialize each read/modify/write, the same discipline the price watches use. */
function createSerializedMutation(load: () => Promise<ShortlistItem[]>, write: (rows: ShortlistItem[]) => Promise<void>) {
  let tail: Promise<void> = Promise.resolve();
  return (update: (current: ShortlistItem[]) => ShortlistItem[]): Promise<ShortlistItem[]> => {
    const operation = tail.then(async () => {
      const next = update(await load());
      await write(next);
      return next;
    });
    tail = operation.then(() => undefined, () => undefined);
    return operation;
  };
}

const mutateShortlist = createSerializedMutation(loadShortlist, save);

/** Add or refresh one product on the shortlist. Returns the new list. */
export function addShortlistItem(input: ShortlistInput): Promise<ShortlistItem[]> {
  return mutateShortlist((list) => upsertShortlistItem(list, input));
}

export function removeFromShortlist(id: string): Promise<ShortlistItem[]> {
  return mutateShortlist((list) => removeShortlistItem(list, id));
}
