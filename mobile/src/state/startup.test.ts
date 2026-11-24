import type { Profile } from '@/api/endpoints';
import { ApiError, SignedOutError } from '@/api/problem';

import { shouldRetry, stageFor } from './startup';

jest.mock('@/api/client', () => ({ auth: {}, api: {} }));

const ok = <T>(data: T) => ({ status: 'success' as const, data });
const pending = { status: 'pending' as const };
const failed = { status: 'error' as const };

const profile = (safetyScreenedAt: string | null) =>
  ({ safety_screened_at: safetyScreenedAt }) as Profile;

describe('stageFor', () => {
  it('waits while signing in or loading the profile', () => {
    expect(stageFor(pending, pending)).toBe('loading');
    expect(stageFor(ok(true), pending)).toBe('loading');
  });

  it('shows the error screen if either step failed', () => {
    expect(stageFor(failed, pending)).toBe('error');
    expect(stageFor(ok(true), failed)).toBe('error');
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
