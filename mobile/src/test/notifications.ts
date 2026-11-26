/**
 * A fake of expo-notifications for tests (jest.setup.js swaps it in): permission as the
 * test sets it, and scheduled reminders kept in a list to check.
 */
type Permission = { granted: boolean; canAskAgain: boolean };
type Scheduled = { content: unknown; trigger: Record<string, unknown> };

let permission: Permission = { granted: false, canAskAgain: true };
let answer = true; // what the person taps when asked
export const scheduled: Scheduled[] = [];
export const asked = { count: 0 };

export function resetNotifications(options: { granted?: boolean; canAskAgain?: boolean; willAllow?: boolean } = {}) {
  permission = { granted: options.granted ?? false, canAskAgain: options.canAskAgain ?? true };
  answer = options.willAllow ?? true;
  scheduled.length = 0;
  asked.count = 0;
}

export const AndroidImportance = { DEFAULT: 5 };
export const SchedulableTriggerInputTypes = { WEEKLY: 'weekly', DAILY: 'daily' };

export function setNotificationHandler(): void {}
export async function setNotificationChannelAsync(): Promise<null> {
  return null;
}
export async function getPermissionsAsync(): Promise<Permission> {
  return permission;
}
export async function requestPermissionsAsync(): Promise<Permission> {
  asked.count += 1;
  permission = { granted: answer, canAskAgain: false };
  return permission;
}
export async function scheduleNotificationAsync(request: Scheduled): Promise<string> {
  scheduled.push(request);
  return String(scheduled.length);
}
export async function cancelAllScheduledNotificationsAsync(): Promise<void> {
  scheduled.length = 0;
}
export async function getAllScheduledNotificationsAsync(): Promise<Scheduled[]> {
  return [...scheduled];
}
