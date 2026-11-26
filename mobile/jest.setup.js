// Runs before every test file (package.json "jest.setupFiles"). Native modules that have
// no stand-in in Jest are swapped for small fakes in src/test/.
jest.mock('expo-sqlite/kv-store', () => jest.requireActual('./src/test/kv-store'));
jest.mock('expo-network', () => jest.requireActual('./src/test/network'));
jest.mock('expo-notifications', () => jest.requireActual('./src/test/notifications'));
jest.mock('expo-audio', () => jest.requireActual('./src/test/audio'));
jest.mock('expo-haptics', () => jest.requireActual('./src/test/haptics'));
jest.mock('@expo-google-fonts/rubik', () => jest.requireActual('./src/test/fonts'));
jest.mock('expo-file-system', () => jest.requireActual('./src/test/files'));
jest.mock('expo-sharing', () => jest.requireActual('./src/test/files'));
