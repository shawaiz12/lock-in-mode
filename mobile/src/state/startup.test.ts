import type { Profile } from '@/api/endpoints';
import { ApiError, SignedOutError } from '@/api/problem';

import { shouldRetry, stageFor } from './startup';

jest.mock('@/api/client', () => ({ auth: {}, api: {} }));

const ok = <T>(data: T) => ({ status: 'success' as const, data });
const pending = { status: 'pending' as const };
const failed = { status: 'error' as const };

const profile = (safetyScreenedAt: string | null, pactDue?: boolean) =>
  ({ safety_screened_at: safetyScreenedAt, pact_due: pactDue }) as Profile;

describe('stageFor', () => {
  it('waits while signing in or loading the profile', () => {
    expect(stageFor(pending, pending)).toBe('loading');
    expect(stageFor(ok(true), pending)).toBe('loading');
  });

  it('shows the error screen if either step failed', () => {
    expect(stageFor(failed, pending)).toBe('error');
    expect(stageFor(ok(true), failed)).toBe('error');
  });

  it('offline with nothing saved: connect once', () => {
    expect(stageFor(ok(true), pending, false)).toBe('offline');
    expect(stageFor(pending, pending, false)).toBe('loading'); // the sign-in check needs no network
  });

  it('what the phone saved carries on, even when refreshing it failed (offline)', () => {
    const saved = { status: 'error' as const, data: profile('2026-11-24T10:00:00Z'), error: new TypeError('Network request failed') };
    expect(stageFor(ok(true), saved, false)).toBe('plan');
    expect(stageFor(ok(true), ok(profile('2026-11-24T10:00:00Z')), false)).toBe('plan');
  });

  it('an ended sign-in always stops at the error screen, saved profile or not', () => {
    const ended = { status: 'error' as const, data: profile('2026-11-24T10:00:00Z'), error: new SignedOutError() };
    expect(stageFor(ok(true), ended)).toBe('error');
  });

  it('the pact comes after the safety check, only when the server says it is due', () => {
    expect(stageFor(ok(true), ok(profile('2026-11-24T10:00:00Z', true)))).toBe('pact');
    expect(stageFor(ok(true), ok(profile('2026-11-24T10:00:00Z', false)))).toBe('plan');
    // A copy saved by the app before the pact existed has no pact_due: never the pact.
    expect(stageFor(ok(true), ok(profile('2026-11-24T10:00:00Z')), false)).toBe('plan');
  });

  it('sends new people to onboarding, then the safety check, then the plan', () => {
    expect(stageFor(ok(true), ok(null))).toBe('onboarding');
    expect(stageFor(ok(true), ok(profile(null)))).toBe('safety');
    expect(stageFor(ok(true), ok(profile('2026-11-24T10:00:00Z')))).toBe('plan');
  });
});

describe('shouldRetry', () => {
  it('retries network failures and server errors twice', () => {
    expect(shouldRetry(0, new TypeError('Network request failed'))).toBe(true);
    expect(shouldRetry(1, new ApiError(503, 'internal_error'))).toBe(true);
    expect(shouldRetry(2, new ApiError(503, 'internal_error'))).toBe(false);
  });

  it("never retries what retrying can't fix", () => {
    expect(shouldRetry(0, new ApiError(404, 'not_found'))).toBe(false);
    expect(shouldRetry(0, new ApiError(429, 'rate_limited'))).toBe(false);
    expect(shouldRetry(0, new SignedOutError())).toBe(false);
  });
});
