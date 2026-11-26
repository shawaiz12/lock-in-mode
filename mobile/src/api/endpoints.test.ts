import { api } from './client';
import {
  deleteAccount,
  deleteSet,
  getBestsTotal,
  getMuscles,
  signPact,
  finishSession,
  getOpenSessionOrNull,
  getOrCreatePlan,
  getProfileOrNull,
  logSet,
  type Profile,
  profileWithChanges,
  saveDisplayName,
  sayWhereItHurts,
  startNextBlock,
  startSession,
} from './endpoints';
import { ApiError } from './problem';

jest.mock('./client', () => ({
  api: { GET: jest.fn(), POST: jest.fn(), PUT: jest.fn(), PATCH: jest.fn(), DELETE: jest.fn() },
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

describe('the workout player', () => {
  const where = { sessionId: 's1', plannedExerciseId: 'pe1', setNumber: 2 };

  it('no workout in progress is not an error (404 session_not_found)', async () => {
    client.GET.mockResolvedValueOnce(problem(404, 'session_not_found') as never);

    expect(await getOpenSessionOrNull()).toBeNull();
  });

  it('starting and continuing are the same call, with the phone’s start time', async () => {
    client.POST.mockResolvedValueOnce(ok({ id: 's1', sets: [] }) as never);

    expect(await startSession('w1', '2026-11-25T10:00:00.000Z')).toEqual({ id: 's1', sets: [] });
    expect(client.POST).toHaveBeenCalledWith('/api/v1/sessions', {
      body: { workout_id: 'w1', started_at: '2026-11-25T10:00:00.000Z' },
    });
  });

  it('ticks a set with a PUT to its own address', async () => {
    client.PUT.mockResolvedValueOnce(ok({ set_number: 2 }) as never);

    await logSet(where, { reps: 10, weight_kg: 20, seconds: null, logged_at: '2026-11-25T10:05:00.000Z' });

    expect(client.PUT).toHaveBeenCalledWith('/api/v1/sessions/{session_id}/sets/{planned_exercise_id}/{set_number}', {
      params: { path: { session_id: 's1', planned_exercise_id: 'pe1', set_number: 2 } },
      body: { reps: 10, weight_kg: 20, seconds: null, logged_at: '2026-11-25T10:05:00.000Z' },
    });
  });

  it('unticking succeeds on 204 (no body) and fails on an error', async () => {
    client.DELETE.mockResolvedValueOnce({ data: undefined, response: new Response(null, { status: 204 }) } as never);
    await expect(deleteSet(where)).resolves.toBeUndefined();

    client.DELETE.mockResolvedValueOnce(problem(409, 'session_finished') as never);
    await expect(deleteSet(where)).rejects.toMatchObject({ code: 'session_finished' });
  });

  it('a skipped "How did that feel?" is sent as null, never as "just right"', async () => {
    client.POST.mockResolvedValueOnce(ok({ id: 's1' }) as never);

    await finishSession('s1', null, '2026-11-25T10:40:00.000Z');

    expect(client.POST).toHaveBeenCalledWith('/api/v1/sessions/{session_id}/finish', {
      params: { path: { session_id: 's1' } },
      body: { feedback: null, finished_at: '2026-11-25T10:40:00.000Z' },
    });
  });

  it('"Where does it hurt?" passes on the limit to offer', async () => {
    client.PATCH.mockResolvedValueOnce(ok({ suggest_limit: 'knees' }) as never);
    expect(await sayWhereItHurts('x1', 'knees')).toBe('knees');

    client.PATCH.mockResolvedValueOnce(ok({ suggest_limit: null }) as never);
    expect(await sayWhereItHurts('x1', 'other')).toBeNull();
  });

  it('a double tap on "start the next block" reads the block the first tap made', async () => {
    client.POST.mockResolvedValueOnce(problem(409, 'plan_in_progress') as never);
    client.GET.mockResolvedValueOnce(ok({ id: 'p2' }) as never);

    expect(await startNextBlock(true)).toEqual({ id: 'p2' });
    expect(client.POST).toHaveBeenCalledWith('/api/v1/plans', { body: { level_up: true } });
  });
});

describe('the redesign’s calls (ADR 0036)', () => {
  it('reads the muscle map and the bests count', async () => {
    client.GET.mockResolvedValueOnce(ok({ groups: [] }) as never);
    client.GET.mockResolvedValueOnce(ok({ total: 9 }) as never);

    expect(await getMuscles()).toEqual({ groups: [] });
    expect(await getBestsTotal()).toBe(9);
    expect(client.GET).toHaveBeenNthCalledWith(1, '/api/v1/me/muscles');
    expect(client.GET).toHaveBeenNthCalledWith(2, '/api/v1/me/bests');
  });

  it('signs the pact', async () => {
    client.POST.mockResolvedValueOnce(ok({ pact_signed_at: '2026-11-26T10:00:00Z' }) as never);

    expect(await signPact()).toEqual({ pact_signed_at: '2026-11-26T10:00:00Z' });
    expect(client.POST).toHaveBeenCalledWith('/api/v1/me/pact');
  });

  it('deletes the account, with the optional reason only when there is one', async () => {
    client.DELETE.mockResolvedValue({ response: new Response(null, { status: 204 }) } as never);

    await deleteAccount('no_time');
    await deleteAccount(null);

    expect(client.DELETE).toHaveBeenNthCalledWith(1, '/api/v1/me', { params: { query: { reason: 'no_time' } } });
    expect(client.DELETE).toHaveBeenNthCalledWith(2, '/api/v1/me', { params: { query: {} } });
  });

  it('a refused delete is an error, not a fresh start', async () => {
    client.DELETE.mockResolvedValueOnce(problem(500, 'internal_error') as never);

    await expect(deleteAccount(null)).rejects.toBeInstanceOf(ApiError);
  });
});
