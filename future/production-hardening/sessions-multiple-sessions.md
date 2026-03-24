# plain-sessions: Multiple Session Support

Allow users to maintain multiple authenticated sessions and switch between them.

## Implementation

- Keep `sessionid` cookie as the active session
- Add `available_sessions` cookie with list of session keys: `["key1", "key2"]`
- On login while authenticated: save current session to available list, create new session
- New `switch_session(request, session_key)` function to switch active session
- New `logout_all(request)` to clear all sessions
- Modified `logout(request)` optionally auto-switches to another available session
- SessionMiddleware reads/writes both cookies
- Setting: `MAX_AVAILABLE_SESSIONS = 5` (default)

## Security Notes

- When logging in as different user, use `flush()` instead of `cycle_key()` to create new session
- Only cycle key when re-authenticating as same user
- Clean up expired sessions from available list in middleware
- Use same cookie security settings for both cookies

## Open Questions

- How should this relate to the existing impersonation feature?
- Should we store session metadata (username, etc.) for UI display?
- UI integration: account switcher component vs. API only?
