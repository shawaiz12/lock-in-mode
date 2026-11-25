/**
 * A fake of expo-sqlite's key-value store for tests (jest.setup.js swaps it in): a Map in
 * memory, with the same sync and async calls the app uses. `resetStorage()` empties it
 * between tests.
 */
const items = new Map<string, string>();

export function resetStorage(): void {
  items.clear();
}

export function storedItem(key: string): string | null {
  return items.get(key) ?? null;
}

const Storage = {
  getItemSync: (key: string): string | null => items.get(key) ?? null,
  setItemSync: (key: string, value: string): void => {
    items.set(key, value);
  },
  removeItemSync: (key: string): boolean => items.delete(key),
  getItem: async (key: string): Promise<string | null> => items.get(key) ?? null,
  setItem: async (key: string, value: string): Promise<void> => {
    items.set(key, value);
  },
  removeItem: async (key: string): Promise<void> => {
    items.delete(key);
  },
};

export const AsyncStorage = Storage;
export { Storage };
export default Storage;
