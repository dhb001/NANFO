# Authentication API

## Purpose
Define authentication and authorization flow contracts.

## Scope
- Login, refresh, logout, and profile endpoints
- Token lifecycle and expiry policy
- RBAC permission model expectations

## Dependency
- Feature-level requirements are defined in `docs/features/Authentication.md`.

## Session Contract

Login and refresh return the canonical envelope containing a TokenPair:
`access_token`, `refresh_token`, `token_type="bearer"`, `expires_in` (seconds).
The refresh request remains `{ "refresh_token": "..." }`. Both tokens must be
replaced atomically. Logout uses the current access token and revokes its entire
session family. Tokens require explicit token type and session ID. Old tokens
without a live Redis family are rejected. Replay of a consumed refresh token
revokes that family. See `docs/project/FoundationSecurity-Step1-Step2.md`.
