/**
 * Signing in and keeping the sign-in alive (ADR 0005, ADR 0027).
 *
 * - First launch: no tokens saved, so start as a guest (POST /auth/guest). No account
 *   wall before the first workout (docs/onboarding.md, screen 0).
 * - Every API call goes through `authedFetch`, which adds "Authorization: Bearer ...".
 * - Access tokens last 15 minutes. Shortly before that, or if the API says 401 anyway,
 *   swap the refresh token for a new pair (POST /auth/refresh) and send the call again.
 * - Refresh tokens are single use (rotation + reuse detection): two refreshes at once
 *   with the same token would look like theft and sign the user out. So only ONE
 *   refresh runs at a time; everyone else waits for it (`refreshing`).
 *
 * - A brand-new guest is a new, empty account: `ensureSignedIn` says so (returns true),
 *   so the app throws away anything it saved for the previous one.
 * - When a sign-in ends for good (the refresh token is refused: the account was erased,
 *   or the token was reused), `onSignedOut` listeners hear it at once, wherever the call
 *   came from (a screen, the workout journal).
 *
 * Everything it needs is passed in (`AuthDeps`), so tests can fake the network, the
 * storage and the clock. .NET: a DelegatingHandler on HttpClient with constructor
 * injection, plus a SemaphoreSlim around the refresh.
 */
import type { components } from './schema';
import { MissingApiUrlError, problemFrom, SignedOutError } from './problem';
import type { StoredTokens, TokenStore } from './tokens';

type TokenPair = components['schemas']['TokenPair'];

export type AuthDeps = {
  baseUrl: string;
  store: TokenStore;
  fetch: (request: Request) => Promise<Response>;
  /** ms since 1970. */
  now: () => number;
};

/** Refresh this long before the access token runs out, so a call never starts stale. */
export const REFRESH_EARLY_MS = 30_000;

export function createAuth(deps: AuthDeps) {
  // undefined: not read from storage yet. null: read, nothing there.
  let cached: StoredTokens | null | undefined;
  let refreshing: Promise<StoredTokens> | null = null;
  const signedOutListeners = new Set<() => void>();

  async function current(): Promise<StoredTokens | null> {
    if (cached === undefined) cached = await deps.store.load();
    return cached;
  }

  async function save(pair: TokenPair): Promise<StoredTokens> {
    const tokens: StoredTokens = {
      accessToken: pair.access_token,
      refreshToken: pair.refresh_token,
      accessExpiresAt: deps.now() + pair.expires_in * 1000,
    };
    await deps.store.save(tokens);
    cached = tokens;
    return tokens;
  }

  function post(path: string, body?: object): Promise<Response> {
    if (!deps.baseUrl) throw new MissingApiUrlError();
    return deps.fetch(
      new Request(`${deps.baseUrl}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    );
  }

  /** Make sure there is a sign-in: the saved one, or a brand-new guest.
   * Returns true when it's a brand-new guest (a new, empty account). */
  async function ensureSignedIn(): Promise<boolean> {
    if (await current()) return false;
    const response = await post('/api/v1/auth/guest');
    if (!response.ok) throw await problemFrom(response);
    await save((await response.json()) as TokenPair);
    return true;
  }

  function refresh(): Promise<StoredTokens> {
    refreshing ??= (async () => {
      try {
        const tokens = await current();
        if (!tokens) throw new SignedOutError();
        const response = await post('/api/v1/auth/refresh', {
          refresh_token: tokens.refreshToken,
        });
        if (response.status === 401) {
          // invalid_refresh_token: this sign-in is over for good. Forget it.
          await deps.store.clear();
          cached = null;
          for (const listener of [...signedOutListeners]) listener();
          throw new SignedOutError();
        }
        // Anything else (no connection, 5xx, 429): keep the tokens and let the caller
        // retry later. The refresh token wasn't used up.
        if (!response.ok) throw await problemFrom(response);
        return await save((await response.json()) as TokenPair);
      } finally {
        refreshing = null;
      }
    })();
    return refreshing;
  }

  function withToken(request: Request, accessToken: string): Request {
    const headers = new Headers(request.headers);
    headers.set('Authorization', `Bearer ${accessToken}`);
    return new Request(request, { headers });
  }

  /** The `fetch` the API client uses for every call except sign-in itself. */
  async function authedFetch(request: Request): Promise<Response> {
    let tokens = await current();
    if (!tokens) throw new SignedOutError();
    if (tokens.accessExpiresAt - deps.now() < REFRESH_EARLY_MS) tokens = await refresh();

    // A request body can be read only once: keep a copy in case we must send it again.
    const retry = request.clone();
    const first = await deps.fetch(withToken(request, tokens.accessToken));
    if (first.status !== 401) return first;

    // 401 anyway (clock skew, server restarted with a new key...). If another call
    // refreshed while this one was in flight, use its token; otherwise refresh now.
    const latest = await current();
    const fresh =
      latest && latest.accessToken !== tokens.accessToken ? latest : await refresh();
    return deps.fetch(withToken(retry, fresh.accessToken));
  }

  /** Forget the sign-in on this phone (after "Your sign-in has ended"). */
  async function forget(): Promise<void> {
    await deps.store.clear();
    cached = null;
  }

  /** Hear about a sign-in that just ended for good. Returns the unsubscribe. */
  function onSignedOut(listener: () => void): () => void {
    signedOutListeners.add(listener);
    return () => {
      signedOutListeners.delete(listener);
    };
  }

  return { ensureSignedIn, authedFetch, forget, onSignedOut };
}

export type Auth = ReturnType<typeof createAuth>;
