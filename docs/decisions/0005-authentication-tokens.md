# 0005 – Authentication: guest + Google/Apple sign-in, our own JWT access tokens and rotating refresh tokens

**Date:** 2026-11-13
**Status:** Accepted

## Context
Users must be able to start immediately as a **guest** (no account), and later save
their progress with **Google** or **Sign in with Apple**. Sign in with Apple is
required on iOS because we offer Google sign-in. We don't store passwords and don't
pay for an auth provider (brief §3.8).

Google and Apple both give the mobile app an **ID token**: a JWT they sign, saying
"this is user X". The backend must verify it and then identify the user with tokens
of its own. Three decisions had to be made:

1. How refresh tokens work (can we log users out? what if one is stolen?)
2. How our access tokens are signed
3. What happens when a guest signs in with a Google/Apple account that already
   belongs to another user

## How it works
- `POST /api/v1/auth/guest` creates a user with `is_guest = true` and returns tokens.
- `POST /api/v1/auth/google` and `/auth/apple` receive the provider's ID token. The
  backend checks the signature against the provider's public keys (JWKS), the issuer,
  the audience (must be *our* app's client ID / bundle ID) and expiry, then finds or
  creates the user by the provider's `sub` and returns **our** tokens.
- Every API request sends `Authorization: Bearer <access token>`.
- `POST /api/v1/auth/refresh` exchanges a refresh token for a new pair.

## Options considered

### Decision 1 – Refresh tokens

#### A. Refresh tokens are JWTs, nothing stored
- ✅ No table, no database lookup.
- ❌ No logout or revocation: a stolen refresh token works until it expires (weeks).

#### B. Random opaque tokens, stored hashed, rotated on every use (chosen)
- ✅ Logout and "log out everywhere" are possible.
- ✅ Rotation + reuse detection: each refresh issues a new token and marks the old one
  used. If a used token is presented again, it was copied, so the whole token family
  is revoked and both the thief and the real user must sign in again.
- ✅ Only a SHA-256 hash is stored, so a database leak doesn't leak working tokens.
  A fast hash is enough because the tokens are 256-bit random values, not guessable
  passwords (bcrypt/argon2 slowness only matters for low-entropy secrets).
- ❌ One table and one indexed lookup per refresh (about one per active user every
  15 minutes): negligible.

### Decision 2 – Signing our access tokens

#### A. HS256 with one secret (chosen)
- ✅ Simplest correct choice when the same service both issues and verifies tokens.
- ❌ Anything that verifies tokens must also hold the secret.

#### B. RS256 / EdDSA key pair
- ✅ Other services could verify tokens with only the public key.
- ❌ Key-pair management for no current benefit: the Django admin has its own login
  and Celery workers never verify tokens.

### Decision 3 – Guest signs in with an account that already belongs to another user

- **(i) Sign into the existing account; this device's guest progress is not carried
  over** (the app warns first). *(chosen for MVP)*
- (ii) Merge guest progress into the existing account: XP, sessions, streaks and plans
  all need conflict rules. Complex and easy to get wrong.
- (iii) Refuse and ask the user: extra screens and confusing.

*How the app learns about the conflict in time to warn: see [ADR 0006](0006-linking-guest-to-provider-account.md).*

When the provider account is **new**, the guest user is simply upgraded: the
`google_sub`/`apple_sub` is attached, `is_guest` becomes false, and all progress is kept.

## Decision
- **Refresh tokens: option B.** Table `refresh_tokens(id, user_id, family_id,
  token_hash UNIQUE, expires_at, used_at, revoked_at, created_at)`; `user_id` is a FK
  to `users` with ON DELETE CASCADE.
- **Access tokens: HS256**, claims `sub` (user id), `iss = lock-in-mode-api`, `iat`,
  `exp`, `type = access`. Decoding accepts **only** HS256 and requires all claims.
- **Lifetimes:** access token 15 minutes; refresh token 60 days, renewed on every
  refresh (active users effectively stay signed in).
- **Account conflict: option (i).**
- **Libraries:** PyJWT for our tokens, and PyJWT's `PyJWKClient` to verify both Google
  and Apple ID tokens (one code path for both providers).
- **Secret handling:** `JWT_SECRET` comes from the environment, is a `SecretStr`, must be
  at least 32 characters, and has no default, so the API refuses to start without a
  real one. Settings errors never echo input values (`hide_input_in_errors`).

## Consequences
- ✅ Logout, "log out everywhere" and stolen-token detection are all possible.
- ✅ No paid services. Google sign-in is free.
- ⚠️ **A guest's refresh token is their only credential.** Uninstalling the app or
  clearing its storage loses a guest account. That's why the app prompts guests to
  save their progress with Google/Apple.
- ⚠️ **Concurrent refreshes look like reuse.** If the app sends two refresh requests
  with the same token at the same moment, the second one revokes the family and logs
  the user out. The mobile app must refresh one request at a time (single-flight).
  The backend locks the token row while rotating (`SELECT ... FOR UPDATE`) so two
  requests can never both succeed.
- ⚠️ A stolen **access** token stays valid for up to 15 minutes; revocation only acts
  on refresh tokens. This is the standard trade-off for not hitting the database on
  every request.
- ⚠️ Rotating `JWT_SECRET` invalidates every access token at once (users silently
  refresh; refresh tokens are unaffected because they aren't JWTs).
- ⚠️ `migrations/env.py` imports the settings, so running migrations now also requires
  `JWT_SECRET` to be set.
- 💰 **Sign in with Apple needs the Apple Developer Program ($99/year)** for real IDs.
  Verification is built and tested now with locally generated keys; the account is
  only needed when the iOS app ships (already budgeted in the brief).
- 🔁 Easy to reverse: switching to RS256 later means a new key and one setting.
