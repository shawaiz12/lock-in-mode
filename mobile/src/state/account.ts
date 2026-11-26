/**
 * Settings → Your data (ADR 0024, 0027, 0036): download everything, or delete the account.
 *
 * - Download: GET /me/export becomes one JSON file in the phone's cache folder, then the
 *   phone's own share sheet opens (save to Files or Drive, send it anywhere). Nothing is
 *   kept after that: the cache folder is the phone's to clear.
 * - Delete: a guest is erased on the server at once; then this phone starts again as a
 *   brand-new guest (`useStartOver`), so nothing of the old account is left on it.
 * .NET: like a small application service the Settings page calls.
 */
import { useMutation } from '@tanstack/react-query';
import { File, Paths } from 'expo-file-system';
import * as Sharing from 'expo-sharing';

import { deleteAccount, exportMyData, type LeavingReason } from '@/api/endpoints';
import { useStartOver } from '@/state/startup';

export const EXPORT_FILE = 'lock-in-mode-data.json';

/** Writes the export to a file and offers it. Returns false if this phone can't share. */
export async function shareMyData(): Promise<boolean> {
  const data = await exportMyData();
  const file = new File(Paths.cache, EXPORT_FILE);
  file.create({ overwrite: true });
  await file.write(JSON.stringify(data, null, 2));
  if (!(await Sharing.isAvailableAsync())) return false;
  await Sharing.shareAsync(file.uri, {
    mimeType: 'application/json',
    UTI: 'public.json',
    dialogTitle: 'Your Lock In Mode data',
  });
  return true;
}

export function useDownloadMyData() {
  return useMutation({ mutationFn: shareMyData });
}

export function useDeleteAccount() {
  const startOver = useStartOver();
  return useMutation({
    mutationFn: (reason: LeavingReason | null) => deleteAccount(reason),
    onSuccess: () => startOver(),
  });
}
