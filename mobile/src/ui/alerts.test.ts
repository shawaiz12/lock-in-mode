import { act, renderHook } from '@testing-library/react-native';
import { setAudioModeAsync, useAudioPlayer } from 'expo-audio';
import { Vibration } from 'react-native';

import { forgetFeel, setFeel } from '@/state/feel';
import { resetStorage } from '@/test/kv-store';

import { useAlerts, useSoundCheck } from './alerts';

type FakePlayer = { currentTime: number; seekTo: jest.Mock; play: jest.Mock };
const mockPlayers: FakePlayer[] = [];

jest.mock('expo-audio', () => ({
  setAudioModeAsync: jest.fn(async () => {}),
  useAudioPlayer: jest.fn(() => {
    const player = { currentTime: 0, seekTo: jest.fn(async () => {}), play: jest.fn() };
    mockPlayers.push(player);
    return player;
  }),
  useAudioPlayerStatus: jest.fn(() => ({ isLoaded: true, playing: false })),
}));
jest.mock('expo-haptics', () => ({ impactAsync: jest.fn(async () => {}), ImpactFeedbackStyle: { Light: 'light' } }));

beforeEach(() => {
  resetStorage();
  forgetFeel();
  mockPlayers.length = 0;
  jest.spyOn(Vibration, 'vibrate').mockImplementation(() => {});
});

it('beeps even with the ringer on silent, and never stops their music', async () => {
  await renderHook(() => useAlerts());

  expect(setAudioModeAsync).toHaveBeenCalledWith({ playsInSilentMode: true, interruptionMode: 'mixWithOthers' });
});

it('saves both sounds on the phone first, so they play offline too', async () => {
  await renderHook(() => useAlerts());

  expect(useAudioPlayer).toHaveBeenCalledWith(expect.anything(), { downloadFirst: true });
});

it('a fresh sound just plays; only a sound that has played is rewound first', async () => {
  const { result } = await renderHook(() => useAlerts());
  const done = mockPlayers[1];
  if (!done) throw new Error('no player');

  await act(async () => result.current.done());
  expect(done.seekTo).not.toHaveBeenCalled();
  expect(done.play).toHaveBeenCalledTimes(1);

  done.currentTime = 0.54; // it played to the end
  await act(async () => result.current.done());
  expect(done.seekTo).toHaveBeenCalledWith(0);
  expect(done.play).toHaveBeenCalledTimes(2);
});

it('time up = beep and buzz; a failing motor never breaks the workout', async () => {
  const vibrate = jest.spyOn(Vibration, 'vibrate').mockImplementation(() => {
    throw new Error('no motor');
  });
  const { result } = await renderHook(() => useAlerts());

  expect(() => result.current.done()).not.toThrow();
  expect(vibrate).toHaveBeenCalled();
});

it('the sound check plays the beep and says whether it loaded', async () => {
  const { result } = await renderHook(() => useSoundCheck());

  expect(result.current.loaded).toBe(true);
  await act(async () => result.current.play());
  expect(mockPlayers[0]?.play).toHaveBeenCalled();
});

it('Settings can switch the beep off: the buzz still comes (ADR 0036)', async () => {
  const { result } = await renderHook(() => useAlerts());
  const [tick, done] = mockPlayers;
  setFeel({ beep: false });
  jest.mocked(Vibration.vibrate).mockClear();

  await act(async () => result.current.countIn());
  await act(async () => result.current.done());

  expect(tick?.play).not.toHaveBeenCalled();
  expect(done?.play).not.toHaveBeenCalled();
  expect(Vibration.vibrate).toHaveBeenCalled();
});

it('Settings can switch vibration off: the beep still plays, no buzz, no tap', async () => {
  const { impactAsync } = jest.requireMock<{ impactAsync: jest.Mock }>('expo-haptics');
  const { result } = await renderHook(() => useAlerts());
  const done = mockPlayers[1];
  setFeel({ vibration: false });
  jest.mocked(Vibration.vibrate).mockClear(); // calls from earlier tests
  impactAsync.mockClear();

  await act(async () => result.current.done());
  await act(async () => result.current.ticked());

  expect(done?.play).toHaveBeenCalled();
  expect(Vibration.vibrate).not.toHaveBeenCalled();
  expect(impactAsync).not.toHaveBeenCalled();
});
