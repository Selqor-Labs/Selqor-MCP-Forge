# Dashboard Authentication Module Integration

Selqor Forge no longer ships with built-in Keycloak authentication.
The dashboard now uses a placeholder hook so teams can integrate their preferred auth stack.

## Integration Point

Implement your auth logic in:

- `src/selqor_forge/dashboard/middleware.py`
- Function: `get_current_user(request: Request) -> CurrentUser | None`

Current default behavior:

- Returns `None` for every request.
- Core dashboard APIs continue to work without user authentication.
- Auth-specific endpoints return `501 AUTH_MODULE_NOT_INTEGRATED`.

## Expected Contract

Your implementation should:

1. Validate incoming credentials/session (JWT, cookie session, API gateway headers, etc.).
2. Return `CurrentUser(...)` for authenticated users.
3. Return `None` for anonymous mode if you want public access.
4. Raise an HTTPException when authentication fails.

## Auth-Specific Endpoints

The following endpoints depend on user authentication context:

- `GET /api/auth/me`
- `GET /api/auth/context`
- `GET /api/users/me/onboarding-status`
- `GET /api/users/me/pending-invites`
- `POST /api/users/me/invites/{id}/accept`
- `POST /api/users/me/invites/{id}/decline`
- `POST /api/organizations`

When no auth module is integrated, these endpoints return `501`.

## Optional Metadata Endpoint

`GET /api/auth/config` returns placeholder metadata for client-side checks:

- `enabled: false`
- `provider: "anonymous"`
- `message: "Dashboard is open — no authentication required."`
