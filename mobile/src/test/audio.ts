/**
 * A fake of expo-audio for tests (jest.setup.js swaps it in): players that do nothing.
 * src/ui/alerts.test.ts brings its own fake to check what's played.
 */
const player = () => ({ currentTime: 0, seekTo: async () => {}, play: () => {}, pause: () => {} });

export async function setAudioModeAsync(): Promise<void> {}
export function useAudioPlayer() {
  return player();
}
export function useAudioPlayerStatus() {
  return { isLoaded: true, playing: false };
}
