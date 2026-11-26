/**
 * "Sound and feel" (ADR 0036, his ask from ADR 0034's planning): the rest beep and the
 * vibration can each be switched off. Settings of THIS phone, not the account: they stay
 * when a new account starts, and need no connection.
 *
 * Kept in the phone's key-value store and read synchronously, so the player never waits.
 * `useFeel` redraws a screen when a switch changes.
 * .NET/Unity: like two PlayerPrefs bools with an "on changed" event.
 */
import Storage from 'expo-sqlite/kv-store';
import { useSyncExternalStore } from 'react';

export type Feel = { beep: boolean; vibration: boolean };

export const FEEL_KEY = 'lockin.feel';
const DEFAULTS: Feel = { beep: true, vibration: true };

let current: Feel | null = null;
const listeners = new Set<() => void>();

function read(): Feel {
  try {
    const saved = Storage.getItemSync(FEEL_KEY);
    if (!saved) return DEFAULTS;
    const parsed = JSON.parse(saved) as Partial<Feel>;
    return {
      beep: typeof parsed.beep === 'boolean' ? parsed.beep : DEFAULTS.beep,
      vibration: typeof parsed.vibration === 'boolean' ? parsed.vibration : DEFAULTS.vibration,
    };
  } catch {
    return DEFAULTS; // unreadable: the defaults, never a broken workout
  }
}

export function getFeel(): Feel {
  if (current === null) current = read();
  return current;
}

export function setFeel(change: Partial<Feel>): void {
  current = { ...getFeel(), ...change };
  try {
    Storage.setItemSync(FEEL_KEY, JSON.stringify(current));
  } catch {
    // kept in memory for now; saved next time
  }
  listeners.forEach((listener) => listener());
}

/** Tests start from what's in the (fake) storage. */
export function forgetFeel(): void {
  current = null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useFeel(): Feel {
  return useSyncExternalStore(subscribe, getFeel, getFeel);
}
