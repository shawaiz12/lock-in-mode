/**
 * The root of the app: shared services, then the navigator.
 *
 * Expo Router turns files in src/app/ into screens: src/app/plan.tsx is "/plan".
 * .NET: like Razor Pages' folder routing; this file is Program.cs + the main layout.
 *
 * Only ONE group of screens is unlocked at a time, from `useStartup().stage`
 * (src/state/startup.ts). When the stage changes (onboarding saved, safety check done),
 * the locked screen disappears and Expo Router moves the person to the open one: no
 * screen ever has to remember to navigate after saving.
 *
 * Offline (ADR 0033): the query cache is saved on the phone and read back at launch
 * (PersistQueryClientProvider, src/state/persist.ts), the workout in progress lives in
 * the journal (src/state/journal.tsx), and expo-network tells both when the phone is
 * online (src/state/online.ts).
 */
import { useFonts } from '@expo-google-fonts/rubik';
import { type QueryClient, useQueryClient } from '@tanstack/react-query';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { Stack } from 'expo-router';
import Storage from 'expo-sqlite/kv-store';
import { StatusBar } from 'expo-status-bar';
import * as SystemUI from 'expo-system-ui';
import { type ReactNode, useEffect, useState } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { deleteSet, finishSession, logSet, startSession } from '@/api/endpoints';
import type { Journal } from '@/features/offline/journal';
import { createJournalStore, JournalProvider } from '@/state/journal';
import { watchConnection } from '@/state/online';
import { showRemindersInTheApp } from '@/state/reminders';
import { persistOptions } from '@/state/persist';
import { keys, makeQueryClient, useStartup } from '@/state/startup';
import { font, FONT_FILES, usePalette } from '@/ui/theme';

watchConnection();
showRemindersInTheApp();

export default function RootLayout() {
  // One cache for the app's whole life (useState keeps it across redraws).
  const [queryClient] = useState(makeQueryClient);
  // Rubik first (a moment, from the app itself); if a font fails, the phone's own font.
  const [fontsLoaded, fontError] = useFonts(FONT_FILES);
  const palette = usePalette();
  useEffect(() => {
    // The colour behind every screen (seen during transitions), light or dark.
    try {
      SystemUI.setBackgroundColorAsync(palette.ground).catch(() => {});
    } catch {
      // not available here (tests): the screens have their own background anyway
    }
  }, [palette.ground]);
  if (!fontsLoaded && !fontError) return null;
  return (
    <SafeAreaProvider>
      <PersistQueryClientProvider client={queryClient} persistOptions={persistOptions}>
        <Journals>
          <StatusBar style={palette.dark ? 'light' : 'dark'} />
          <Navigator />
        </Journals>
      </PersistQueryClientProvider>
    </SafeAreaProvider>
  );
}

/** What the server says changed once the journal's start or finish arrives. */
function refresh(queryClient: QueryClient, before: Journal | null, after: Journal | null) {
  if (!after) return;
  if (after.sessionId && !before?.sessionId) {
    void queryClient.invalidateQueries({ queryKey: keys.openSession });
  }
  if (after.done && !before?.done) {
    void queryClient.invalidateQueries({ queryKey: keys.plan });
    void queryClient.invalidateQueries({ queryKey: keys.openSession });
    void queryClient.invalidateQueries({ queryKey: keys.workout(after.workoutId) });
    void queryClient.invalidateQueries({ queryKey: keys.week });
    void queryClient.invalidateQueries({ queryKey: keys.xp });
    void queryClient.invalidateQueries({ queryKey: keys.muscles });
    void queryClient.invalidateQueries({ queryKey: keys.bests });
  }
}

/** The journal of the workout in progress, for the whole app, sending in the background. */
function Journals({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [store] = useState(() =>
    createJournalStore({
      storage: Storage,
      api: { start: startSession, logSet, deleteSet, finish: finishSession },
      onChange: (before, after) => refresh(queryClient, before, after),
    }),
  );
  useEffect(() => store.attach(), [store]);
  return <JournalProvider store={store}>{children}</JournalProvider>;
}

function Navigator() {
  const { stage } = useStartup();
  const palette = usePalette();
  const waiting = stage === 'loading' || stage === 'error' || stage === 'offline';
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: palette.ground },
        headerStyle: { backgroundColor: palette.ground },
        headerTintColor: palette.text,
        headerShadowVisible: false,
        headerTitleStyle: { fontFamily: font.heavy },
        animation: 'fade',
      }}
    >
      <Stack.Protected guard={waiting}>
        <Stack.Screen name="index" />
      </Stack.Protected>
      <Stack.Protected guard={stage === 'onboarding'}>
        <Stack.Screen name="onboarding" />
      </Stack.Protected>
      <Stack.Protected guard={stage === 'safety'}>
        <Stack.Screen name="safety" />
      </Stack.Protected>
      <Stack.Protected guard={stage === 'pact'}>
        <Stack.Screen name="pact" />
      </Stack.Protected>
      <Stack.Protected guard={stage === 'plan'}>
        <Stack.Screen name="plan" />
        <Stack.Screen name="settings" options={{ animation: 'slide_from_right' }} />
        <Stack.Screen
          name="workout/[id]/index"
          options={{ headerShown: true, title: '', animation: 'slide_from_right' }}
        />
        {/* The player has its own "Leave" button; a stray swipe mid-set shouldn't leave. */}
        <Stack.Screen
          name="workout/[id]/play"
          options={{ animation: 'slide_from_bottom', gestureEnabled: false }}
        />
      </Stack.Protected>
    </Stack>
  );
}
