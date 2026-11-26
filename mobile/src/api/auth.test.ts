import { createAuth, REFRESH_EARLY_MS } from './auth';
import { ApiError, SignedOutError } from './problem';
import type { StoredTokens, TokenStore } from './tokens';

const BASE = 'https://api.test';
const NOW = 1_800_000_000_000;

function memoryStore(initial: StoredTokens | null = null) {
  let saved = initial;
  const store: TokenStore & { saved: () => StoredTokens | null } = {
    load: jest.fn(async () => saved),
    save: jest.fn(async (tokens: StoredTokens) => {
      saved = tokens;
    }),
    clear: jest.fn(async () => {
      saved = null;
    }),
    saved: () => saved,
  };
  return store;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function pair(n: number) {
  return { access_token: `access-${n}`, refresh_token: `refresh-${n}`, expires_in: 900 };
}

const tokens = (n: number, expiresInMs = 600_000): StoredTokens => ({
  accessToken: `access-${n}`,
  refreshToken: `refresh-${n}`,
  accessExpiresAt: NOW + expiresInMs,
});

/** A fake server: records every request; `handler` decides the answer. */
function fakeServer(handler: (request: Request) => Response | Promise<Response>) {
  const requests: Request[] = [];
  const fetch = jest.fn(async (request: Request) => {
    requests.push(request);
    return handler(request);
  });
  return { fetch, requests };
}

const path = (request: Request) => new URL(request.url).pathname;
const bearer = (request: Request) => request.headers.get('Authorization');

function setup(store: ReturnType<typeof memoryStore>, handler: Parameters<typeof fakeServer>[0]) {
  const server = fakeServer(handler);
  const auth = createAuth({ baseUrl: BASE, store, fetch: server.fetch, now: () => NOW });
  return { auth, ...server };
}

describe('ensureSignedIn', () => {
  it('starts as a guest when nothing is saved, saves the sign-in, says it is new', async () => {
    const store = memoryStore();
    const { auth, requests } = setup(store, () => json(201, pair(1)));

    expect(await auth.ensureSignedIn()).toBe(true);

    expect(requests.map(path)).toEqual(['/api/v1/auth/guest']);
    expect(store.saved()).toEqual({
      accessToken: 'access-1',
      refreshToken: 'refresh-1',
      accessExpiresAt: NOW + 900_000,
    });
  });

  it('keeps the saved sign-in (no new guest on every launch)', async () => {
    const { auth, requests } = setup(memoryStore(tokens(1)), () => json(500, {}));

    expect(await auth.ensureSignedIn()).toBe(false);

    expect(requests).toHaveLength(0);
  });

  it('reports a refused guest sign-in with its problem code', async () => {
    const { auth } = setup(memoryStore(), () =>
      json(429, { code: 'rate_limited', detail: 'Too many attempts.' }),
    );

    const error = await auth.ensureSignedIn().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 429, code: 'rate_limited' });
  });
});

describe('authedFetch', () => {
  it('adds the access token', async () => {
    const { auth, requests } = setup(memoryStore(tokens(1)), () => json(200, {}));

    const response = await auth.authedFetch(new Request(`${BASE}/api/v1/me`));

    expect(response.status).toBe(200);
    expect(bearer(requests[0]!)).toBe('Bearer access-1');
  });

  it('refreshes first when the access token is about to run out', async () => {
    const store = memoryStore(tokens(1, REFRESH_EARLY_MS - 1));
    const { auth, requests } = setup(store, (request) =>
      path(request) === '/api/v1/auth/refresh' ? json(200, pair(2)) : json(200, {}),
    );

    await auth.authedFetch(new Request(`${BASE}/api/v1/me`));

    expect(requests.map(path)).toEqual(['/api/v1/auth/refresh', '/api/v1/me']);
    expect(await requests[0]!.json()).toEqual({ refresh_token: 'refresh-1' });
    expect(bearer(requests[1]!)).toBe('Bearer access-2');
    expect(store.saved()?.refreshToken).toBe('refresh-2');
  });

  it('on a 401, refreshes once and sends the same call again, body included', async () => {
    const { auth, requests } = setup(memoryStore(tokens(1)), (request) => {
      if (path(request) === '/api/v1/auth/refresh') return json(200, pair(2));
      return bearer(request) === 'Bearer access-1' ? json(401, {}) : json(200, { ok: true });
    });

    const response = await auth.authedFetch(
      new Request(`${BASE}/api/v1/me/profile`, { method: 'PUT', body: '{"goal":"strength"}' }),
    );

    expect(await response.json()).toEqual({ ok: true });
    expect(requests.map(path)).toEqual([
      '/api/v1/me/profile',
      '/api/v1/auth/refresh',
      '/api/v1/me/profile',
    ]);
    expect(requests[2]!.method).toBe('PUT');
    expect(await requests[2]!.text()).toBe('{"goal":"strength"}');
  });

  it('gives up after one retry (a second 401 goes back to the caller)', async () => {
    const { auth, requests } = setup(memoryStore(tokens(1)), (request) =>
      path(request) === '/api/v1/auth/refresh' ? json(200, pair(2)) : json(401, {}),
    );

    const response = await auth.authedFetch(new Request(`${BASE}/api/v1/me`));

    expect(response.status).toBe(401);
    expect(requests).toHaveLength(3);
  });

  it('runs ONE refresh for calls that all need it at once (refresh tokens are single use)', async () => {
    let release!: () => void;
    const refreshGate = new Promise<void>((resolve) => (release = resolve));
    const { auth, requests } = setup(memoryStore(tokens(1, 0)), async (request) => {
      if (path(request) === '/api/v1/auth/refresh') {
        await refreshGate;
        return json(200, pair(2));
      }
      return json(200, {});
    });

    const calls = [1, 2, 3].map(() => auth.authedFetch(new Request(`${BASE}/api/v1/me`)));
    release();
    await Promise.all(calls);

    expect(requests.filter((r) => path(r) === '/api/v1/auth/refresh')).toHaveLength(1);
    expect(requests.filter((r) => path(r) === '/api/v1/me').map(bearer)).toEqual([
      'Bearer access-2',
      'Bearer access-2',
      'Bearer access-2',
    ]);
  });

  it('uses a token another call just refreshed instead of refreshing again', async () => {
    let refreshes = 0;
    let release!: () => void;
    const slowFirstCall = new Promise<void>((resolve) => (release = resolve));
    const { auth } = setup(memoryStore(tokens(1)), async (request) => {
      if (path(request) === '/api/v1/auth/refresh') {
        refreshes += 1;
        return json(200, pair(refreshes + 1));
      }
      if (path(request) === '/api/v1/slow' && bearer(request) === 'Bearer access-1') {
        await slowFirstCall;
        return json(401, {});
      }
      return bearer(request) === 'Bearer access-1' ? json(401, {}) : json(200, {});
    });

    const slow = auth.authedFetch(new Request(`${BASE}/api/v1/slow`));
    await auth.authedFetch(new Request(`${BASE}/api/v1/fast`)); // 401 -> refresh -> access-2
    release();
    const response = await slow; // its 401 arrives after: reuse access-2

    expect(response.status).toBe(200);
    expect(refreshes).toBe(1);
  });

  it('forgets the sign-in when the refresh token is refused, and says so', async () => {
    const store = memoryStore(tokens(1, 0));
    const { auth } = setup(store, () => json(401, { code: 'invalid_refresh_token' }));
    const heard = jest.fn();
    const stop = auth.onSignedOut(heard);

    await expect(auth.authedFetch(new Request(`${BASE}/api/v1/me`))).rejects.toBeInstanceOf(
      SignedOutError,
    );
    expect(store.saved()).toBeNull();
    expect(heard).toHaveBeenCalledTimes(1);

    stop();
    await expect(auth.authedFetch(new Request(`${BASE}/api/v1/me`))).rejects.toBeInstanceOf(
      SignedOutError,
    );
    expect(heard).toHaveBeenCalledTimes(1); // unsubscribed (and no sign-in left to end)
  });

  it('keeps the sign-in when the refresh fails for another reason (offline, 5xx)', async () => {
    const store = memoryStore(tokens(1, 0));
    const { auth } = setup(store, () => json(503, { code: 'internal_error' }));
    const heard = jest.fn();
    auth.onSignedOut(heard);

    await expect(auth.authedFetch(new Request(`${BASE}/api/v1/me`))).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(store.saved()?.refreshToken).toBe('refresh-1');
    expect(heard).not.toHaveBeenCalled();
  });

  it('refuses to call the API with no sign-in at all', async () => {
    const { auth, requests } = setup(memoryStore(), () => json(200, {}));

    await expect(auth.authedFetch(new Request(`${BASE}/api/v1/me`))).rejects.toBeInstanceOf(
      SignedOutError,
    );
    expect(requests).toHaveLength(0);
  });
});

describe('forget', () => {
  it('clears the saved sign-in so the next start is a new guest', async () => {
    const store = memoryStore(tokens(1));
    const { auth, requests } = setup(store, () => json(201, pair(5)));

    await auth.forget();
    await auth.ensureSignedIn();

    expect(requests.map(path)).toEqual(['/api/v1/auth/guest']);
    expect(store.saved()?.accessToken).toBe('access-5');
  });
});
