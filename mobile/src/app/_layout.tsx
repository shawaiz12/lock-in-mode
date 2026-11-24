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
 */
import { QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useState } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { makeQueryClient, useStartup } from '@/state/startup';
import { colors } from '@/ui/kit';

export default function RootLayout() {
  // One cache for the app's whole life (useState keeps it across redraws).
  const [queryClient] = useState(makeQueryClient);
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={queryClient}>
        <StatusBar style="light" />
        <Navigator />
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}

function Navigator() {
  const { stage } = useStartup();
  const waiting = stage === 'loading' || stage === 'error';
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.background },
        headerStyle: { backgroundColor: colors.background },
        headerTintColor: colors.text,
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
      <Stack.Protected guard={stage === 'plan'}>
        <Stack.Screen name="plan" />
        <Stack.Screen
          name="workout/[id]"
          options={{ headerShown: true, title: '', animation: 'slide_from_right' }}
        />
      </Stack.Protected>
    </Stack>
  );
}
