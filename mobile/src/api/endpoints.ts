/**
 * Every API call the app makes, as plain async functions. Screens never call `api`
 * directly: they use these (through TanStack Query), so the "what does a 404 mean here"
 * rules from docs/errors.md live in one place.
 * .NET: a small service class over the generated client.
 */
import { api } from './client';
import { isApiError, toApiError } from './problem';
import type { components } from './schema';

type Schemas = components['schemas'];
export type Profile = Schemas['ProfileRead'];
export type ProfileWrite = Schemas['ProfileWrite'];
export type SafetyScreen = Schemas['SafetyScreen'];
export type Plan = Schemas['PlanRead'];
export type WorkoutSummary = Schemas['WorkoutSummary'];
export type WorkoutDetail = Schemas['WorkoutDetail'];
export type PlannedExercise = Schemas['PlannedExerciseRead'];

/** openapi-fetch returns { data } or { error }; this turns the error into an ApiError. */
function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined) return result.data;
  throw toApiError(result.response.status, result.error);
}

/** The onboarding answers, or null before onboarding is done (404 profile_not_found). */
export async function getProfileOrNull(): Promise<Profile | null> {
  try {
    return unwrap(await api.GET('/api/v1/me/profile'));
  } catch (error) {
    if (isApiError(error, 'profile_not_found')) return null;
    throw error;
  }
}

/** PUT replaces the whole profile (send every answer). Changed answers rebuild an
 * untouched plan on the server (ADR 0017). */
export async function saveProfile(profile: ProfileWrite): Promise<Profile> {
  return unwrap(await api.PUT('/api/v1/me/profile', { body: profile }));
}

/** The optional name from the welcome screen. */
export async function saveDisplayName(name: string): Promise<void> {
  unwrap(await api.PATCH('/api/v1/me', { body: { display_name: name } }));
}

/** Only the result is stored on the server, never the four answers (ADR 0012). */
export async function submitSafetyScreen(answers: SafetyScreen): Promise<Profile> {
  return unwrap(await api.POST('/api/v1/me/safety-screen', { body: answers }));
}

export type CurrentPlan = { plan: Plan; justCreated: boolean };

/** The current plan; on the very first visit there is none yet, so build it
 * (POST /plans) and say so, for the "Building your plan" reveal. */
export async function getOrCreatePlan(): Promise<CurrentPlan> {
  try {
    return { plan: unwrap(await api.GET('/api/v1/plans/current')), justCreated: false };
  } catch (error) {
    if (!isApiError(error, 'plan_not_found')) throw error;
  }
  try {
    return { plan: unwrap(await api.POST('/api/v1/plans', { body: null })), justCreated: true };
  } catch (error) {
    // Two screens asked at once and the other one built it first: just read it.
    if (!isApiError(error, 'plan_in_progress')) throw error;
    return { plan: unwrap(await api.GET('/api/v1/plans/current')), justCreated: false };
  }
}

export async function getWorkout(workoutId: string): Promise<WorkoutDetail> {
  return unwrap(
    await api.GET('/api/v1/workouts/{workout_id}', {
      params: { path: { workout_id: workoutId } },
    }),
  );
}

/** A full PUT body from what the server has, with some answers changed. Used by the
 * plan screen's small choices (shoulder day, bro split). */
export function profileWithChanges(profile: Profile, changes: Partial<ProfileWrite>): ProfileWrite {
  return {
    goal: profile.goal,
    level: profile.level,
    location: profile.location,
    equipment: profile.equipment,
    limits: profile.limits,
    days_per_week: profile.days_per_week,
    minutes_per_session: (profile.minutes_per_session ?? null) as ProfileWrite['minutes_per_session'],
    women_home_track: profile.women_home_track,
    prefers_bro_split: profile.prefers_bro_split,
    shoulder_day: profile.shoulder_day,
    obstacles: profile.obstacles,
    ...changes,
  };
}
