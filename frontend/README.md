# Owner Console (Part C)
React + TypeScript SPA, mobile-first, Hinglish-friendly. Talks to the deployed backend.

Build:
- Lifecycle feed from GET /events?property_id= and GET /bookings?property_id= (live-ish: realtime or poll).
- "Ask the Assistant" box -> POST /ask -> show answer + the SQL it ran (for data questions).
- Loading / empty / error states everywhere.

Set the backend base URL via an env var (e.g. VITE_BACKEND_URL). Deploy on Vercel/Netlify/HF.
Scaffold with Vite (react-ts). Keep business logic in the backend.
