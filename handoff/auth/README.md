# Sign-in, favorites and history

Drop-in React + Firebase code. `npm install firebase` first.

| File | What it is |
|---|---|
| `firebase.ts` | Starts Firebase from six `VITE_FIREBASE_*` variables. Exports `auth`, `db`, `configured`. |
| `profile.ts` | `useUser()` gives the signed-in user. `useProfile(user)` gives `profile`, `toggleFavorite(station)`, `recordSearch(station, date)`, `clearHistory()`, `mostVisited`, `sync`. |
| `Account.tsx` | The sign-in button and panel: email and password, create account, Google, sign out. |
| `account.css` | Styles for the panel, chips, star and history row. Uses the CSS variables `--ink`, `--paper`, `--rule`, `--accent`, `--mono`, `--sans`, `--display`, `--ease`, `--r`. |
| `firestore.rules` | Paste into Firebase console > Firestore > Rules. Each user can read and write only `users/{their uid}`. |

## Use
```tsx
const { user } = useUser()
const prof = useProfile(user)

<Account user={user} sync={prof.sync} />                      // in the header
prof.recordSearch(stationCode, isoDate)                        // whenever the user picks a station or a day
prof.toggleFavorite(stationCode)                               // star button
prof.profile.favorites, prof.mostVisited, prof.profile.searches
```

## Setup
1. `.env.local` (not committed) and Vercel > Settings > Environment Variables, the same six names:
   `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID`, `VITE_FIREBASE_STORAGE_BUCKET`, `VITE_FIREBASE_MESSAGING_SENDER_ID`, `VITE_FIREBASE_APP_ID`. These are public identifiers, not secrets.
2. Firebase console > Authentication > Sign-in method: turn on Email/Password and Google.
3. Authentication > Settings > Authorized domains: add the Vercel domain, or Google sign-in is refused.
4. Create a Firestore database and paste in `firestore.rules`.

## How it stores things
Signed out: this browser only. Signed in: `users/{uid}` in Firestore, mirrored locally, so it follows the user across devices. If Firestore cannot be reached it keeps working locally and `sync` says so.

Status: compiles in a Vite + React + TypeScript project. Not yet tested against the live Firebase project.
