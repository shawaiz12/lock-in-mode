/**
 * What the phone does at the end of a rest or a timed move: a beep and a buzz (his
 * choice, ADR 0032), so nobody has to watch the screen between sets. Short beeps at
 * 3, 2, 1 seconds say "get ready".
 *
 * - The beep plays even with the ringer on silent (his choice after trying it, ADR 0032:
 *   at the gym the phone is often on silent, and the beep is the point), and alongside
 *   their music ("mixWithOthers": the music keeps going). The phone's volume buttons
 *   still set how loud it is.
 * - The buzz is the phone's vibration motor (React Native's Vibration), stronger than a
 *   haptic tap, so it's felt with the phone on the floor or in a pocket.
 * - A tick of a set gets a light haptic tap: the button really did something.
 *
 * Any of these can fail (low power mode, no motor, audio busy): never let that break
 * the workout, so every call is fire-and-forget. While developing, a failure is written
 * to the Metro terminal ("[alerts] …") instead of disappearing.
 *
 * The sounds are saved on the phone before they're needed (`downloadFirst`, ADR 0034):
 * in Expo Go they otherwise stream from the computer, so a workout opened offline was
 * silent. A rewind only happens after a sound has played (rewinding a sound that hasn't
 * loaded yet can stop it from playing at all). `useSoundCheck` plays the beep on demand
 * and shows whether the sound loaded, to check a phone.
 * .NET/Unity: like an AudioSource + Handheld.Vibrate() wrapped in one small service.
 */
import { type AudioPlayer, setAudioModeAsync, useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import * as Haptics from 'expo-haptics';
import { useEffect } from 'react';
import { Vibration } from 'react-native';

const TICK = require('../../assets/sounds/tick.wav');
const DONE = require('../../assets/sounds/done.wav');

/** Beep on silent too; never stop their music. */
export const AUDIO_MODE = { playsInSilentMode: true, interruptionMode: 'mixWithOthers' } as const;

/** Seen in the Metro terminal while developing; silent in a real build. */
const report = (error: unknown) => {
  if (__DEV__) console.warn('[alerts]', error);
};

const quietly = (work: () => unknown) => {
  try {
    const result = work();
    if (result instanceof Promise) result.catch(report);
  } catch (error) {
    // A beep or a buzz is a nicety; the workout carries on without it.
    report(error);
  }
};

/** Saved on the phone first, then played from there. */
const OPTIONS = { downloadFirst: true } as const;

function play(player: AudioPlayer) {
  quietly(async () => {
    // Back to the start only once it has played: a fresh sound is already there.
    if (player.currentTime > 0) await player.seekTo(0);
    player.play();
  });
}

export type Alerts = {
  /** 3, 2, 1: a short beep. */
  countIn: () => void;
  /** Time's up: the long beep and a buzz. */
  done: () => void;
  /** A set was ticked: a light tap. */
  ticked: () => void;
};

export function useAlerts(): Alerts {
  const tick = useAudioPlayer(TICK, OPTIONS);
  const done = useAudioPlayer(DONE, OPTIONS);

  useEffect(() => {
    quietly(() => setAudioModeAsync(AUDIO_MODE));
  }, []);

  return {
    countIn: () => play(tick),
    done: () => {
      play(done);
      quietly(() => Vibration.vibrate([0, 400, 150, 400]));
    },
    ticked: () => quietly(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)),
  };
}

/** "Sound check" (ADR 0034): play the rest beep now and say whether its sound loaded,
 * to find out why a phone stays quiet. */
export function useSoundCheck() {
  const done = useAudioPlayer(DONE, OPTIONS);
  const status = useAudioPlayerStatus(done);
  useEffect(() => {
    quietly(() => setAudioModeAsync(AUDIO_MODE));
  }, []);
  return {
    loaded: status.isLoaded,
    playing: status.playing,
    play: () => {
      play(done);
      quietly(() => Vibration.vibrate(200));
    },
  };
}
