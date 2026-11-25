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
 * the workout, so every call is fire-and-forget.
 * .NET/Unity: like an AudioSource + Handheld.Vibrate() wrapped in one small service.
 */
import { setAudioModeAsync, useAudioPlayer } from 'expo-audio';
import * as Haptics from 'expo-haptics';
import { useEffect } from 'react';
import { Vibration } from 'react-native';

const TICK = require('../../assets/sounds/tick.wav');
const DONE = require('../../assets/sounds/done.wav');

/** Beep on silent too; never stop their music. */
export const AUDIO_MODE = { playsInSilentMode: true, interruptionMode: 'mixWithOthers' } as const;

const quietly = (work: () => unknown) => {
  try {
    const result = work();
    if (result instanceof Promise) result.catch(() => {});
  } catch {
    // A beep or a buzz is a nicety; the workout carries on without it.
  }
};

export type Alerts = {
  /** 3, 2, 1: a short beep. */
  countIn: () => void;
  /** Time's up: the long beep and a buzz. */
  done: () => void;
  /** A set was ticked: a light tap. */
  ticked: () => void;
};

export function useAlerts(): Alerts {
  const tick = useAudioPlayer(TICK);
  const done = useAudioPlayer(DONE);

  useEffect(() => {
    quietly(() => setAudioModeAsync(AUDIO_MODE));
  }, []);

  const play = (player: typeof tick) =>
    quietly(async () => {
      await player.seekTo(0);
      player.play();
    });

  return {
    countIn: () => play(tick),
    done: () => {
      play(done);
      quietly(() => Vibration.vibrate([0, 400, 150, 400]));
    },
    ticked: () => quietly(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)),
  };
}
