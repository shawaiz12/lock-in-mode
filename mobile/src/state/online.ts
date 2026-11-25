/**
 * Is the phone online? (ADR 0033)
 *
 * TanStack Query has one switch for this (`onlineManager`). While it says offline,
 * queries don't try the network: they keep showing what's saved on the phone and wait,
 * then refresh by themselves once it says online again. On a phone nothing flips that
 * switch by itself, so `watchConnection` feeds it from expo-network.
 *
 * "Connected" isn't always "online" (Wi-Fi with no internet): only a network the phone
 * KNOWS can't reach the internet counts as offline. Anything unsure counts as online, and
 * a request that fails is simply tried again later.
 * .NET: like NetworkChange.NetworkAvailabilityChanged feeding one app-wide flag.
 */
import { onlineManager } from '@tanstack/react-query';
import { addNetworkStateListener, getNetworkStateAsync, type NetworkState } from 'expo-network';
import { useSyncExternalStore } from 'react';

export function isOnlineState(state: NetworkState): boolean {
  return state.isConnected !== false && state.isInternetReachable !== false;
}

/** Call once at startup. */
export function watchConnection(): void {
  onlineManager.setEventListener((setOnline) => {
    const subscription = addNetworkStateListener((state) => setOnline(isOnlineState(state)));
    getNetworkStateAsync()
      .then((state) => setOnline(isOnlineState(state)))
      .catch(() => {});
    return () => subscription.remove();
  });
}

/** Redraws the screen when the phone goes online or offline. */
export function useOnline(): boolean {
  return useSyncExternalStore(
    (onChange) => onlineManager.subscribe(onChange),
    () => onlineManager.isOnline(),
  );
}
