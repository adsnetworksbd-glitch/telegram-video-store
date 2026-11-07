# Phase 12 — Part 2A notes

Done: Admin shell + routing (permission-gated), Dashboard, Video list / add / edit / hide / publish, Category list / add / edit / hide / recount, backup source (backend + form), dashboard stats / top videos / recent orders / recent activity.

Limits (kept on purpose):
- Thumbnails are managed as https URLs with a live preview; there is no file upload (no storage service exists in the project).
- Videos are archived by hiding, not deleted (data integrity).
- Backup source is stored and returnable via `?backup=true`; the Mini App player does not fall back to it yet (needs a user-app change).

Not verified here: `npm install && npm run build` (no network in the build sandbox) and tests that import pydantic (3 pre-existing environment errors: pydantic missing).
