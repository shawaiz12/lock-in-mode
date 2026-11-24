/**
 * Errors from the API (RFC 9457 problem details, ADR 0007).
 *
 * Every error body has a stable `code` (docs/errors.md). The app branches on `code`,
 * never on the English `title`/`detail`.
 * .NET: like a custom exception carrying ProblemDetails, thrown from a typed HttpClient.
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly detail?: string,
  ) {
    super(detail ?? `${status} ${code}`);
    this.name = 'ApiError';
  }
}

/** The sign-in is over for good (refresh token unknown, expired, revoked or reused). */
export class SignedOutError extends Error {
  constructor() {
    super('Your sign-in has ended.');
    this.name = 'SignedOutError';
  }
}

/** The app was started without EXPO_PUBLIC_API_URL (see mobile/.env.example). */
export class MissingApiUrlError extends Error {
  constructor() {
    super('EXPO_PUBLIC_API_URL is not set. Copy mobile/.env.example to mobile/.env.');
    this.name = 'MissingApiUrlError';
  }
}

type ProblemBody = { code?: unknown; detail?: unknown };

/** Turn any error body the API sent into an ApiError (or a generic one if it isn't JSON). */
export function toApiError(status: number, body: unknown): ApiError {
  const problem = (typeof body === 'object' && body !== null ? body : {}) as ProblemBody;
  const code = typeof problem.code === 'string' ? problem.code : 'http_error';
  const detail = typeof problem.detail === 'string' ? problem.detail : undefined;
  return new ApiError(status, code, detail);
}

/** Read an error response's body without ever throwing while reading it. */
export async function problemFrom(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // Not JSON (a proxy's HTML error page, an empty body): keep the status only.
  }
  return toApiError(response.status, body);
}

export function isApiError(error: unknown, code: string): error is ApiError {
  return error instanceof ApiError && error.code === code;
}

/** Words for the error screen. Kept short: the person only needs to know what to do. */
export function describeError(error: unknown): string {
  if (error instanceof MissingApiUrlError) return error.message;
  if (error instanceof SignedOutError) return error.message;
  if (error instanceof ApiError) {
    if (error.status === 429) return error.detail ?? 'Too many tries. Wait a minute, then try again.';
    if (error.status >= 500) return 'The server is having a moment. Try again shortly.';
    return error.detail ?? 'Something went wrong. Try again.';
  }
  // fetch throws a TypeError ("Network request failed") when there's no connection.
  return "Can't reach Lock In Mode. Check your connection and try again.";
}
