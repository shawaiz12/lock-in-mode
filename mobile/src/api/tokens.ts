/**
 * Where the sign-in lives on the phone: the OS's encrypted storage (Keychain on iOS,
 * Keystore-encrypted storage on Android). Never AsyncStorage: that's plain text.
 *
 * Guests (ADR 0027): this is their ONLY way back into their account. Lose it (Android
 * uninstall, "clear data") and the account becomes a lost guest the server erases.
 * .NET: like ProtectedData / DPAPI for a desktop app's saved credentials.
 */
import * as SecureStore from 'expo-secure-store';

export type StoredTokens = {
  accessToken: string;
  refreshToken: string;
  /** When the access token stops working, in ms since 1970 (phone clock). */
  accessExpiresAt: number;
};

/** An interface, so tests can use an in-memory store (dependency injection). */
export interface TokenStore {
  load(): Promise<StoredTokens | null>;
  save(tokens: StoredTokens): Promise<void>;
  clear(): Promise<void>;
}

// One JSON value under one key: the three parts are always saved together.
// (Keys may only use letters, numbers, ".", "-" and "_".) About 500 bytes, well
// under the ~2 KB some iOS versions accept.
const KEY = 'lockin.session';

function isStoredTokens(value: unknown): value is StoredTokens {
  const v = value as Partial<StoredTokens> | null;
  return (
    typeof v === 'object' &&
    v !== null &&
    typeof v.accessToken === 'string' &&
    typeof v.refreshToken === 'string' &&
    typeof v.accessExpiresAt === 'number'
  );
}

export const secureTokenStore: TokenStore = {
  async load() {
    const raw = await SecureStore.getItemAsync(KEY);
    if (raw === null) return null;
    try {
      const parsed: unknown = JSON.parse(raw);
      return isStoredTokens(parsed) ? parsed : null;
    } catch {
      return null; // unreadable: treat as signed out rather than crash on every start
    }
  },
  async save(tokens) {
    await SecureStore.setItemAsync(KEY, JSON.stringify(tokens));
  },
  async clear() {
    await SecureStore.deleteItemAsync(KEY);
  },
};
