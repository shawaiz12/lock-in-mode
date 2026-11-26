/**
 * Settings (ADR 0036), from the gear on Home:
 *
 *   You             the account and the optional name
 *   Training        the reminder, the sound check
 *   Sound and feel  rest beep and vibration switches (this phone only)
 *   Your data       "Share usage data", "Download my data", "Delete account"
 *
 * Signing out comes with Google/Apple sign-in: a guest who signed out could never get
 * back in, so there's nothing to sign out of yet.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { Text, TextInput, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { type LeavingReason, saveDisplayName, updateMe } from '@/api/endpoints';
import { describeError, isApiError } from '@/api/problem';
import { cleanName } from '@/features/onboarding/flow';
import { useDeleteAccount, useDownloadMyData } from '@/state/account';
import { setFeel, useFeel } from '@/state/feel';
import { useMe } from '@/state/reminders';
import { keys } from '@/state/startup';
import {
  BackButton,
  Body,
  Choice,
  Label,
  LockInButton,
  OutlineButton,
  Row,
  RowGroup,
  Screen,
  Sheet,
  SwitchRow,
  TextButton,
  Title,
} from '@/ui/kit';
import { chunky, font, makeStyles, space, usePalette } from '@/ui/theme';
import { ReminderRows } from '@/ui/week';

export default function Settings() {
  const styles = useStyles();
  const palette = usePalette();
  const me = useMe();
  const feel = useFeel();
  const queryClient = useQueryClient();
  const [naming, setNaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const download = useDownloadMyData();
  const share = useMutation({
    mutationFn: (on: boolean) => updateMe({ share_usage_data: on }),
    onSuccess: (updated) => queryClient.setQueryData(keys.me, updated),
  });

  const name = me.data?.display_name ?? null;
  const sharing = share.isPending ? share.variables : (me.data?.share_usage_data ?? true);

  return (
    <Screen
      header={
        <View style={styles.header}>
          <BackButton onPress={() => router.back()} />
          <Title>Settings</Title>
        </View>
      }
    >
      <View style={styles.account}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{(name ?? 'G').charAt(0).toUpperCase()}</Text>
        </View>
        <View style={styles.grow}>
          <Text style={styles.accountTitle}>{name ? `${name} · guest account` : 'Guest account'}</Text>
          <Text style={styles.accountLine}>Saved to this phone’s sign-in. Google and Apple sign-in come later.</Text>
        </View>
      </View>

      <Label>You</Label>
      <RowGroup>
        <Row title="Your name" value={name ?? 'Not set'} onPress={() => setNaming(true)} last />
      </RowGroup>

      <Label>Training</Label>
      <RowGroup>
        <ReminderRows />
      </RowGroup>

      <Label>Sound and feel</Label>
      <RowGroup>
        <SwitchRow title="Rest beep" value={feel.beep} onChange={(on) => setFeel({ beep: on })} />
        <SwitchRow title="Vibration" value={feel.vibration} onChange={(on) => setFeel({ vibration: on })} last />
      </RowGroup>

      <Label>Your data</Label>
      <RowGroup>
        <SwitchRow
          title="Share usage data"
          value={sharing}
          disabled={!me.data || share.isPending}
          onChange={(on) => share.mutate(on)}
        />
        <Row
          title="Download my data"
          value={download.isPending ? 'Getting it ready…' : 'One file'}
          onPress={() => (download.isPending ? undefined : download.mutate())}
        />
        <Row
          title="Delete account"
          value="Asks first"
          danger
          icon={<TrashIcon color={palette.danger} />}
          onPress={() => setDeleting(true)}
          last
        />
      </RowGroup>
      <Body muted>
        Usage data is which steps people reach (like “finished workout 3”), never your health answers. Turning it
        off also erases what was already saved.
      </Body>
      {share.isError ? <Body>{describeError(share.error)}</Body> : null}
      {download.isError ? <Body>{downloadError(download.error)}</Body> : null}
      {download.data === false ? <Body>This phone can’t share files. Try again on another phone.</Body> : null}

      {naming ? <NameSheet current={name} onClose={() => setNaming(false)} /> : null}
      {deleting ? (
        <DeleteSheet
          onClose={() => setDeleting(false)}
          onDownload={() => download.mutate()}
          downloading={download.isPending}
        />
      ) : null}
    </Screen>
  );
}

function downloadError(error: unknown): string {
  return isApiError(error, 'rate_limited')
    ? 'That’s 3 downloads this hour. Try again in a little while.'
    : describeError(error);
}

function TrashIcon({ color }: { color: string }) {
  return (
    <Svg width={18} height={18} viewBox="0 0 24 24" fill="none">
      <Path
        d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"
        stroke={color}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

function NameSheet({ current, onClose }: { current: string | null; onClose: () => void }) {
  const styles = useStyles();
  const palette = usePalette();
  const queryClient = useQueryClient();
  const [text, setText] = useState(current ?? '');
  const save = useMutation({
    mutationFn: () => saveDisplayName(cleanName(text)),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.me });
      onClose();
    },
  });
  return (
    <Sheet visible onClose={onClose}>
      <Title>Your name</Title>
      <Body muted>Optional. Only you see it, in the app.</Body>
      <TextInput
        style={styles.input}
        value={text}
        onChangeText={setText}
        placeholder="Your name"
        placeholderTextColor={palette.muted}
        maxLength={50}
        autoCapitalize="words"
        returnKeyType="done"
        accessibilityLabel="Your name"
      />
      {save.isError ? <Body>{describeError(save.error)}</Body> : null}
      <LockInButton title="Save" busy={save.isPending} onPress={() => save.mutate()} />
      <TextButton title="Cancel" onPress={onClose} />
    </Sheet>
  );
}

const REASONS: [LeavingReason, string][] = [
  ['too_hard', 'Too hard'],
  ['no_time', 'No time'],
  ['injury', 'An injury'],
  ['switched_apps', 'Using another app'],
  ['privacy', 'Privacy'],
  ['other', 'Something else'],
];

/** "This can't be undone", with what goes, the download offered first, and an optional
 * reason (kept with no link to the person, ADR 0024). */
function DeleteSheet({
  onClose,
  onDownload,
  downloading,
}: {
  onClose: () => void;
  onDownload: () => void;
  downloading: boolean;
}) {
  const styles = useStyles();
  const [reason, setReason] = useState<LeavingReason | null>(null);
  const remove = useDeleteAccount();
  return (
    <Sheet visible onClose={remove.isPending ? () => {} : onClose}>
      <Title>Delete your account?</Title>
      <Body>
        Everything goes, right away: your plan, every workout and set, your bests, XP and streak. This can’t be
        undone.
      </Body>
      <OutlineButton
        title={downloading ? 'Getting your data ready…' : 'Download my data first'}
        disabled={downloading}
        onPress={onDownload}
      />
      <Label>Why are you leaving? (optional)</Label>
      <View style={styles.reasons}>
        {REASONS.map(([value, label]) => (
          <View key={value} style={styles.reason}>
            <Choice
              label={label}
              selected={reason === value}
              onPress={() => setReason(reason === value ? null : value)}
            />
          </View>
        ))}
      </View>
      {remove.isError ? <Body>{describeError(remove.error)}</Body> : null}
      <LockInButton
        title="Delete for good"
        tone="danger"
        busy={remove.isPending}
        onPress={() => remove.mutate(reason)}
      />
      <TextButton title="Keep my account" onPress={onClose} />
    </Sheet>
  );
}

const useStyles = makeStyles((p) => ({
  header: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  grow: { flex: 1 },
  account: {
    ...chunky,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    backgroundColor: p.card,
    borderColor: p.edge,
    borderRadius: 20,
    padding: 14,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 14,
    backgroundColor: p.button,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: { fontFamily: font.heavy, color: p.onButton, fontSize: 18 },
  accountTitle: { fontFamily: font.heavy, color: p.text, fontSize: 16 },
  accountLine: { fontFamily: font.regular, color: p.muted, fontSize: 13, marginTop: 2 },
  input: {
    ...chunky,
    borderColor: p.edge,
    backgroundColor: p.ground,
    borderRadius: 16,
    color: p.text,
    fontFamily: font.regular,
    fontSize: 17,
    paddingVertical: 14,
    paddingHorizontal: space.m,
  },
  reasons: { flexDirection: 'row', flexWrap: 'wrap', gap: space.s },
  reason: { minWidth: '45%', flexGrow: 1 },
}));
