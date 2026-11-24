import { api } from './client';
import {
  getOrCreatePlan,
  getProfileOrNull,
  type Profile,
  profileWithChanges,
  saveDisplayName,
} from './endpoints';
import { ApiError } from './problem';

jest.mock('./client', () => ({
  api: { GET: jest.fn(), POST: jest.fn(), PUT: jest.fn(), PATCH: jest.fn() },
  auth: {},
}));

const client = jest.mocked(api);

/** What openapi-fetch returns: { data } on success, { error } otherwise. */
const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
const problem = (status: number, code: string) => ({
  error: { code, status, title: code, type: '' },
  response: new Response(null, { status }),
});

beforeEach(() => jest.resetAllMocks());

describe('getProfileOrNull', () => {
  it('returns the profile', async () => {
    client.GET.mockResolvedValueOnce(ok({ goal: 'strength' }) as never);

    expect(await getProfileOrNull()).toEqual({ goal: 'strength' });
  });

  it('means "not onboarded yet" on 404 profile_not_found', async () => {
    client.GET.mockResolvedValueOnce(problem(404, 'profile_not_found') as never);

    expect(await getProfileOrNull()).toBeNull();
  });

  it('passes other errors on', async () => {
    client.GET.mockResolvedValueOnce(problem(401, 'invalid_access_token') as never);

    await expect(getProfileOrNull()).rejects.toMatchObject({ code: 'invalid_access_token' });
  });
});

describe('getOrCreatePlan', () => {
  it('reads the current plan', async () => {
    client.GET.mockResolvedValueOnce(ok({ id: 'p1' }) as never);

    expect(await getOrCreatePlan()).toEqual({ plan: { id: 'p1' }, justCreated: false });
    expect(client.POST).not.toHaveBeenCalled();
  });

  it('builds the first plan when there is none', async () => {
    client.GET.mockResolvedValueOnce(problem(404, 'plan_not_found') as never);
    client.POST.mockResolvedValueOnce({ ...ok({ id: 'p1' }) } as never);

    expect(await getOrCreatePlan()).toEqual({ plan: { id: 'p1' }, justCreated: true });
    expect(client.POST).toHaveBeenCalledWith('/api/v1/plans', { body: null });
  });

  it('reads the plan someone else built first (409 plan_in_progress)', async () => {
    client.GET.mockResolvedValueOnce(problem(404, 'plan_not_found') as never);
    client.POST.mockResolvedValueOnce(problem(409, 'plan_in_progress') as never);
    client.GET.mockResolvedValueOnce(ok({ id: 'p1' }) as never);

    expect(await getOrCreatePlan()).toEqual({ plan: { id: 'p1' }, justCreated: false });
  });

  it('never builds a plan after other errors (e.g. safety check missing)', async () => {
    client.GET.mockResolvedValueOnce(problem(409, 'safety_screen_required') as never);

    await expect(getOrCreatePlan()).rejects.toBeInstanceOf(ApiError);
    expect(client.POST).not.toHaveBeenCalled();
  });
});

describe('saveDisplayName', () => {
  it('sends only the name (PATCH leaves the rest as it is)', async () => {
    client.PATCH.mockResolvedValueOnce(ok({}) as never);

    await saveDisplayName('Shawaiz');

    expect(client.PATCH).toHaveBeenCalledWith('/api/v1/me', { body: { display_name: 'Shawaiz' } });
  });
});

describe('profileWithChanges', () => {
  it('keeps every saved answer and changes only what was asked', () => {
    const saved = {
      goal: 'build_muscle',
      level: 'some_experience',
      location: 'home',
      equipment: ['dumbbells'],
      limits: ['back'],
      days_per_week: 6,
      minutes_per_session: null,
      women_home_track: true,
      prefers_bro_split: false,
      shoulder_day: 'push',
      obstacles: ['get_bored'],
      // read-only fields the PUT must not send:
      needs_low_intensity: true,
      safety_screened_at: '2026-11-24T10:00:00Z',
      created_at: '2026-11-24T10:00:00Z',
      updated_at: '2026-11-24T10:00:00Z',
      bro_split_available: false,
    } as Profile;

    expect(profileWithChanges(saved, { shoulder_day: 'legs' })).toEqual({
      goal: 'build_muscle',
      level: 'some_experience',
      location: 'home',
      equipment: ['dumbbells'],
      limits: ['back'],
      days_per_week: 6,
      minutes_per_session: null,
      women_home_track: true,
      prefers_bro_split: false,
      shoulder_day: 'legs',
      obstacles: ['get_bored'],
    });
  });
});
