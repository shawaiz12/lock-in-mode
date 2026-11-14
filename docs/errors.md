# Error codes

Every error from the Lock In Mode API is an [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457)
problem document, sent as `Content-Type: application/problem+json`
([ADR 0007](decisions/0007-error-format-problem-details.md)):

```json
{
  "type": "https://github.com/shawaiz12/lock-in-mode/blob/main/docs/errors.md#provider_account_in_use",
  "title": "Account already in use",
  "status": 409,
  "detail": "This Google account already belongs to another user",
  "code": "provider_account_in_use"
}
```

**Clients branch on `code`.** `title` and `detail` are for people and may change.
`detail` is left out when it would only repeat `title`.

| Code | Status | Meaning | What the app should do |
|---|---|---|---|
| [`not_authenticated`](#not_authenticated) | 401 | No access token sent | Sign in (or start as guest) |
| [`invalid_access_token`](#invalid_access_token) | 401 | Access token expired, invalid, or its user is gone | Refresh once, then retry |
| [`invalid_refresh_token`](#invalid_refresh_token) | 401 | Refresh token unknown, expired, revoked or reused | Sign in again |
| [`invalid_id_token`](#invalid_id_token) | 401 | Google/Apple token didn't verify (or wrong nonce) | Restart the Google/Apple sign-in |
| [`not_found`](#not_found) | 404 | No such endpoint or resource | Bug in the app |
| [`method_not_allowed`](#method_not_allowed) | 405 | Wrong HTTP method | Bug in the app |
| [`provider_account_in_use`](#provider_account_in_use) | 409 | That Google/Apple account belongs to another user | Warn that guest progress stays behind; if confirmed, call `/auth/{provider}` |
| [`provider_already_linked`](#provider_already_linked) | 409 | A different account of that provider is already linked | Don't offer linking again |
| [`validation_failed`](#validation_failed) | 422 | Request body or parameters invalid; see `errors` | Bug in the app |
| [`internal_error`](#internal_error) | 500 | Unexpected server error | Retry later |
| [`provider_unavailable`](#provider_unavailable) | 503 | Google/Apple sign-in is switched off on the server | Hide that sign-in option |
| [`database_unavailable`](#database_unavailable) | 503 | Health check can't reach the database | Retry later |
| [`http_error`](#http_error) | any | Any other HTTP error from the framework | Treat by status code |

## not_authenticated
The request needs `Authorization: Bearer <access token>` and didn't send one.
Sent with `WWW-Authenticate: Bearer`.

## invalid_access_token
The access token is malformed, expired, not signed by us, or its user was deleted.
Access tokens live 15 minutes: refresh once with `POST /api/v1/auth/refresh`, then retry.
Sent with `WWW-Authenticate: Bearer`.

## invalid_refresh_token
The refresh token is unknown, expired or revoked, or was already used. Reuse revokes the
whole sign-in on that device (ADR 0005). The user must sign in again.
Sent with `WWW-Authenticate: Bearer`.

## invalid_id_token
The Google or Apple ID token failed verification: bad signature, wrong app (audience),
expired, or, for Apple, a nonce that doesn't match. Sent with `WWW-Authenticate: Bearer`.

## not_found
No endpoint at this path, or the requested resource doesn't exist.

## method_not_allowed
The path exists but not with this HTTP method. The `Allow` header lists valid methods.

## provider_account_in_use
`POST /api/v1/me/link/{provider}`: the Google/Apple account already belongs to another
user. Nothing changed. Per ADR 0006, the app warns that this device's guest progress won't
come along, and if the user confirms, calls `POST /api/v1/auth/{provider}`.

## provider_already_linked
`POST /api/v1/me/link/{provider}`: this user already has a *different* account of that
provider linked. Unlinking isn't supported yet.

## validation_failed
The body, query or path parameters don't match the schema. The response adds an `errors`
list. Submitted values are never echoed back, because they can contain tokens.

```json
{
  "code": "validation_failed",
  "status": 422,
  "detail": "1 invalid field",
  "errors": [{"location": "body", "field": "nonce", "code": "missing", "message": "Field required"}]
}
```

## internal_error
Something unexpected broke on the server. The response never includes internal details;
the server logs the full error.

## provider_unavailable
That sign-in provider isn't configured on this server (no client id). Hide the button.

## database_unavailable
Returned by `GET /health` when the database can't be reached.

## http_error
Fallback for any other HTTP error raised by the framework; branch on `status`.
