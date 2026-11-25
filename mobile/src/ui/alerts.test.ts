import { renderHook } from '@testing-library/react-native';
import { setAudioModeAsync } from 'expo-audio';
import { Vibration } from 'react-native';

import { useAlerts } from './alerts';

jest.mock('expo-audio', () => ({
  setAudioModeAsync: jest.fn(async () => {}),
  useAudioPlayer: jest.fn(() => ({ seekTo: jest.fn(async () => {}), play: jest.fn() })),
}));
jest.mock('expo-haptics', () => ({ impactAsync: jest.fn(async () => {}), ImpactFeedbackStyle: { Light: 'light' } }));

it('beeps even with the ringer on silent, and never stops their music', async () => {
  await renderHook(() => useAlerts());

  expect(setAudioModeAsync).toHaveBeenCalledWith({ playsInSilentMode: true, interruptionMode: 'mixWithOthers' });
});

it('time up = beep and buzz; a failing motor never breaks the workout', async () => {
  const vibrate = jest.spyOn(Vibration, 'vibrate').mockImplementation(() => {
    throw new Error('no motor');
  });
  const { result } = await renderHook(() => useAlerts());

  expect(() => result.current.done()).not.toThrow();
  expect(vibrate).toHaveBeenCalled();
});
