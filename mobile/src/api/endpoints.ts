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
export type ExerciseDetail = Schemas['ExerciseDetail'];
export type Session = Schemas['SessionRead'];
export type SetLog = Schemas['SetLogRead'];
export type SetLogWrite = Schemas['SetLogWrite'];
export type SessionResult = Schemas['SessionResult'];
export type Feedback = Schemas['Feedback'];
export type SwapReason = Schemas['SwapReason'];
export type SwapResult = Schemas['SwapResult'];
export type BodyArea = Schemas['BodyArea'];
export type BodyLimit = Schemas['BodyLimit'];

/** openapi-fetch returns { data } or { error }; this turns the error into an ApiError. */
function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined) return result.data;
  throw toApiError(result.response.status, result.error);
}

/** For responses with no body (204): success is enough. */
function unwrapEmpty(result: { error?: unknown; response: Response }): void {
  if (result.response.ok) return;
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

/** Steps, cues and the common mistake ("How to do it"), plus the kit (weights or not). */
export async function getExercise(exerciseId: string): Promise<ExerciseDetail> {
  return unwrap(
    await api.GET('/api/v1/exercises/{exercise_id}', {
      params: { path: { exercise_id: exerciseId } },
    }),
  );
}

/** The workout in progress, or null when there is none (404 session_not_found). */
export async function getOpenSessionOrNull(): Promise<Session | null> {
  try {
    return unwrap(await api.GET('/api/v1/sessions/current'));
  } catch (error) {
    if (isApiError(error, 'session_not_found')) return null;
    throw error;
  }
}

/** "Lock In: start". Starts the next workout, or continues it if it's already open (the
 * server answers 201 or 200 with the same session), so calling it twice is safe.
 * 409 not_next_workout: the plan moved on (refresh it). */
export async function startSession(workoutId: string): Promise<Session> {
  return unwrap(await api.POST('/api/v1/sessions', { body: { workout_id: workoutId } }));
}

type SetPath = { sessionId: string; plannedExerciseId: string; setNumber: number };

function setPath({ sessionId, plannedExerciseId, setNumber }: SetPath) {
  return {
    path: { session_id: sessionId, planned_exercise_id: plannedExerciseId, set_number: setNumber },
  };
}

/** Tick a set. PUT: sending it again (a retry, an edit) replaces it. */
export async function logSet(where: SetPath, body: SetLogWrite): Promise<SetLog> {
  return unwrap(
    await api.PUT('/api/v1/sessions/{session_id}/sets/{planned_exercise_id}/{set_number}', {
      params: setPath(where),
      body,
    }),
  );
}

/** Untick a set (a mis-tap). */
export async function deleteSet(where: SetPath): Promise<void> {
  unwrapEmpty(
    await api.DELETE('/api/v1/sessions/{session_id}/sets/{planned_exercise_id}/{set_number}', {
      params: setPath(where),
    }),
  );
}

/** Finish, early or not: it counts either way. No feedback = skipped, never "just right". */
export async function finishSession(sessionId: string, feedback: Feedback | null): Promise<SessionResult> {
  return unwrap(
    await api.POST('/api/v1/sessions/{session_id}/finish', {
      params: { path: { session_id: sessionId } },
      body: { feedback },
    }),
  );
}

/** Skip the next workout (not started). 409 session_in_progress: started, offer finishing. */
export async function skipWorkout(workoutId: string): Promise<void> {
  unwrap(
    await api.POST('/api/v1/workouts/{workout_id}/skip', {
      params: { path: { workout_id: workoutId } },
    }),
  );
}

/** "This hurts, swap it" (for good) or "Show another" (today only), ADR 0020.
 * 409 exercise_changed: a double tap already swapped it. 409 no_other_exercise: "Show
 * another" has nothing else. */
export async function swapExercise(
  workoutId: string,
  plannedExerciseId: string,
  exerciseId: string,
  reason: SwapReason,
): Promise<SwapResult> {
  return unwrap(
    await api.POST('/api/v1/workouts/{workout_id}/exercises/{planned_exercise_id}/swap', {
      params: { path: { workout_id: workoutId, planned_exercise_id: plannedExerciseId } },
      body: { exercise_id: exerciseId, reason },
    }),
  );
}

/** The optional "Where does it hurt?". May come back with a limit to offer after the
 * workout (never during it: changing the profile ends the workout, ADR 0020). */
export async function sayWhereItHurts(exerciseId: string, area: BodyArea): Promise<BodyLimit | null> {
  const result = unwrap(
    await api.PATCH('/api/v1/me/swapped-out/{exercise_id}', {
      params: { path: { exercise_id: exerciseId } },
      body: { body_area: area },
    }),
  );
  return result.suggest_limit ?? null;
}

/** The next block, once this one is complete. `levelUp`: "Ready for more?" said yes.
 * 409 plan_in_progress: a double tap already started it (read the plan instead). */
export async function startNextBlock(levelUp: boolean): Promise<Plan> {
  try {
    return unwrap(await api.POST('/api/v1/plans', { body: { level_up: levelUp } }));
  } catch (error) {
    if (!isApiError(error, 'plan_in_progress')) throw error;
    return unwrap(await api.GET('/api/v1/plans/current'));
  }
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
