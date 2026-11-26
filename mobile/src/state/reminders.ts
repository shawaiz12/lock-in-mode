/**
 * The training reminder (ADR 0034) and the phone's time zone.
 *
 * - The reminder is a LOCAL notification the phone schedules itself (expo-notifications,
 *   works in Expo Go), once a week on each chosen day. No push server, no cost.
 * - It's also saved on the account (PATCH /me), so a new phone, or a reinstall, can set
 *   it up again by itself (`useAccountSync`).
 * - One notification per planned day, never more ("protect the channel": a reminder
 *   people learn to ignore is worse than none). Easy to change or turn off in Settings.
 * - Asking for permission happens when they tap "Remind me", right after a win (workout
 *   1's finish screen), never on first launch.
 * - The time zone goes to the account too, so the week runs Monday to Sunday on their
 *   own calendar.
 * .NET: like a scheduled toast via the OS (Windows ToastNotificationManager), plus a user
 * setting synced to the server.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AndroidImportance,
  cancelAllScheduledNotificationsAsync,
  getAllScheduledNotificationsAsync,
  getPermissionsAsync,
  requestPermissionsAsync,
  SchedulableTriggerInputTypes,
  scheduleNotificationAsync,
  setNotificationChannelAsync,
  setNotificationHandler,
} from 'expo-notifications';
import { useEffect } from 'react';
import { Platform } from 'react-native';

import { getMe, type Me, type Reminder, updateMe } from '@/api/endpoints';
import { parseTime, toPhoneWeekday } from '@/features/week/words';
import { useOnline } from '@/state/online';
import { keys } from '@/state/startup';

const CHANNEL = 'reminders';

/** One line that speaks to the feeling, not to the app (no "we miss you", no guilt). */
export const REMINDER_TEXT = { title: 'Lock In Mode: on', body: 'Your next workout is ready. One tap and you’re in.' };

/** The phone said no to notifications (and can't ask again). */
export class NotificationsOffError extends Error {
  constructor() {
    super('Notifications are off for Lock In Mode');
    this.name = 'NotificationsOffError';
  }
}

/** Show a reminder that arrives while the app is open too, quietly. */
export function showRemindersInTheApp(): void {
  setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: false,
      shouldSetBadge: false,
    }),
  });
}

/** Asks only if it hasn't been answered yet. */
export async function allowNotifications(): Promise<boolean> {
  if (Platform.OS === 'android') {
    // Android 13+ shows the permission prompt only once a channel exists.
    await setNotificationChannelAsync(CHANNEL, {
      name: 'Workout reminders',
      importance: AndroidImportance.DEFAULT,
    });
  }
  const now = await getPermissionsAsync();
  if (now.granted) return true;
  if (!now.canAskAgain) return false;
  return (await requestPermissionsAsync()).granted;
}

/** Replaces whatever was scheduled with this reminder (null: none). */
export async function scheduleReminder(reminder: Reminder | null): Promise<void> {
  await cancelAllScheduledNotificationsAsync();
  if (!reminder) return;
  const { hour, minute } = parseTime(reminder.at);
  for (const day of reminder.days) {
    await scheduleNotificationAsync({
      content: REMINDER_TEXT,
      trigger: {
        type: SchedulableTriggerInputTypes.WEEKLY,
        weekday: toPhoneWeekday(day),
        hour,
        minute,
        channelId: CHANNEL,
      },
    });
  }
}

/** The account (GET /me), kept on the phone like the plan. */
export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: getMe });
}

/** Set, change or turn off (null) the reminder: on the phone first, then the account. */
export function useSaveReminder() {
  const queryClient = useQueryClient();
  return useMutation({
    networkMode: 'always',
    mutationFn: async (reminder: Reminder | null): Promise<Me> => {
      if (reminder && !(await allowNotifications())) throw new NotificationsOffError();
      await scheduleReminder(reminder);
      return updateMe({ reminder });
    },
    onSuccess: (me) => queryClient.setQueryData(keys.me, me),
  });
}

export function deviceTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** Keeps the account and this phone in step, quietly, whenever Home shows online:
 * the time zone (a trip abroad moves the week with them) and the reminder (a new phone
 * gets the saved one; one turned off on another phone stops here too). */
export function useAccountSync(me: Me | undefined) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const zone = deviceTimeZone();
  const savedZone = me?.time_zone;
  const saved = me?.reminder ?? null;
  const reminderKey = saved ? `${saved.at}/${saved.days.join(',')}` : 'none';

  useEffect(() => {
    if (!me || !online || savedZone === zone) return;
    updateMe({ time_zone: zone })
      .then((updated) => {
        queryClient.setQueryData(keys.me, updated);
        return queryClient.invalidateQueries({ queryKey: keys.week });
      })
      .catch(() => {}); // tried again next time Home shows
  }, [me, online, savedZone, zone, queryClient]);

  const hasMe = me !== undefined;
  useEffect(() => {
    if (!hasMe) return;
    // Rebuilt from its key, so the effect runs when the reminder's content changes only.
    const [at = '', days = ''] = reminderKey.split('/');
    const reminder: Reminder | null = reminderKey === 'none' ? null : { at, days: days.split(',').map(Number) };
    void (async () => {
      const scheduled = await getAllScheduledNotificationsAsync();
      if (reminder === null) {
        if (scheduled.length > 0) await cancelAllScheduledNotificationsAsync();
        return;
      }
      const granted = (await getPermissionsAsync()).granted;
      if (granted && scheduled.length !== reminder.days.length) await scheduleReminder(reminder);
    })().catch(() => {});
  }, [hasMe, reminderKey]);
}
