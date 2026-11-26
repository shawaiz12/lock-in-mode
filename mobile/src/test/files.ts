/**
 * Jest stand-ins for expo-file-system and expo-sharing ("Download my data"): files live
 * in a Map, and shares are recorded so a test can check what the person was offered.
 */
export const written = new Map<string, string>();
export const shared: { uri: string; options: unknown }[] = [];
let canShare = true;

export function resetFiles(sharing = true): void {
  written.clear();
  shared.length = 0;
  canShare = sharing;
}

export const Paths = { cache: { uri: 'file:///cache/' }, document: { uri: 'file:///documents/' } };

export class File {
  uri: string;
  constructor(dir: { uri: string }, name: string) {
    this.uri = `${dir.uri}${name}`;
  }
  create(): void {
    written.set(this.uri, '');
  }
  async write(content: string): Promise<void> {
    written.set(this.uri, content);
  }
}

export async function isAvailableAsync(): Promise<boolean> {
  return canShare;
}

export async function shareAsync(uri: string, options?: unknown): Promise<void> {
  shared.push({ uri, options });
}
