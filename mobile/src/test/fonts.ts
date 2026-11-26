/** Jest stand-in for @expo-google-fonts/rubik: no font files to load in a test, so the
 * fonts are "loaded" at once and the app draws straight away. */
export const useFonts = (): [boolean, Error | null] => [true, null];
export const Rubik_400Regular = 1;
export const Rubik_500Medium = 2;
export const Rubik_600SemiBold = 3;
export const Rubik_700Bold = 4;
export const Rubik_800ExtraBold = 5;
