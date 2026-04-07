/** Shared REST base (matches `lib/api.ts` / FastAPI `/api` prefix). */
export const API_BASE = (
  process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api'
).replace(/\/$/, '');
