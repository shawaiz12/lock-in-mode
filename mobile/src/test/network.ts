/**
 * A fake of expo-network for tests (jest.setup.js swaps it in). Online unless a test
 * says otherwise: `setConnected(false)` tells the app the connection is gone, the way the
 * phone would.
 */
type State = { isConnected: boolean; isInternetReachable: boolean; type: string };
type Listener = (state: State) => void;

let state: State = { isConnected: true, isInternetReachable: true, type: 'WIFI' };
const listeners = new Set<Listener>();

export function setConnected(connected: boolean): void {
  state = { isConnected: connected, isInternetReachable: connected, type: connected ? 'WIFI' : 'NONE' };
  for (const listener of listeners) listener(state);
}

export async function getNetworkStateAsync(): Promise<State> {
  return state;
}

export function addNetworkStateListener(listener: Listener) {
  listeners.add(listener);
  return { remove: () => listeners.delete(listener) };
}

export function useNetworkState(): State {
  return state;
}

export const NetworkStateType = { NONE: 'NONE', UNKNOWN: 'UNKNOWN', WIFI: 'WIFI', CELLULAR: 'CELLULAR' };
