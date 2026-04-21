# Dashboard Authentication Integration

Selqor Forge public v1 ships the dashboard as a **local-only single-user tool**.
It does not include shared-user authentication, organizations, or team
management out of the box.

## What The Public Build Does

- `GET /api/auth/config` reports capability metadata for the local-only build
- Shared auth, onboarding, invite, organization, and team-management routes
  return `501 LOCAL_ONLY_BUILD`
- Core local dashboard APIs continue to work without user authentication

## When You Need This Document

Use this guide only if you are adapting Selqor Forge for a shared or untrusted
network. If you are running the public build on your own machine, you do not
need to integrate auth.

## Integration Point

Implement your auth logic in:

- `src/selqor_forge/dashboard/middleware.py`
- `get_current_user(request: Request) -> CurrentUser | None`
- `get_effective_org_id(...) -> str | None` if you need real org scoping

## Expected Contract

Your implementation should:

1. Validate incoming credentials or session state
2. Return `CurrentUser(...)` for authenticated users
3. Return `None` only if you intentionally support anonymous access
4. Raise `HTTPException` when authentication fails
5. Replace the local-only capability metadata from `auth_placeholder_config()`

## Shared-Feature Endpoints To Re-enable

- `GET /api/auth/me`
- `GET /api/auth/context`
- `GET /api/users/me/onboarding-status`
- `GET /api/users/me/pending-invites`
- `POST /api/users/me/invites/{id}/accept`
- `POST /api/users/me/invites/{id}/decline`
- `POST /api/organizations`
- `GET /api/organizations/check`
- `GET /api/settings/team`
- `POST /api/settings/team/invite`
- `GET /api/settings/team/invites`
- `DELETE /api/settings/team/invites/{invite_id}`

## Local-Only Capability Payload

`GET /api/auth/config` currently returns metadata like:

- `enabled: false`
- `provider: "local_only"`
- `local_only: true`
- `organizations_enabled: false`
- `team_management_enabled: false`

If you add real auth, update this payload so the frontend can discover the new
capabilities without guessing.
