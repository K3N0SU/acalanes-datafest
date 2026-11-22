# Site plan: who uses it, and what we're building

Owner: InterstellarApx (site). Data and model: K3N0SU. Written Nov 21, 2026.

## Who uses it, honestly
A commuter can't change their station, and usually can't change much of their schedule. The everyday station-and-hour number on its own doesn't help them: they already know rush hour, and 2025 ridership is about 40 to 50% of 2019 at most stations.

What does help is knowing **when their normal trip won't be normal**, and the one small thing they can do about it:

| What a commuter can actually change | Example |
|---|---|
| The day (hybrid workers) | "Tuesday has a Giants game near your station. Go in Wednesday." |
| About 20 to 30 minutes | "Leave one train earlier", or "stay for a coffee and miss the 10 PM wave" |
| How they ride | Let one packed train pass, skip the bike or stroller that day, take the ferry once |
| Expectations | Knowing tonight will be packed at 10 PM beats a surprise on the platform |

Other people it helps: event-goers ("when do I leave to avoid the post-game crush?"), holiday and airport trips (Thanksgiving week), riders for whom crowds are a real barrier (wheelchair users, strollers, bikes), and BART or event staff planning extra trains and staffing.

**Pitch:** "You can't change your commute. We tell you the one or two days a week it won't go as usual, and the one small thing to do about it."

## What the site will do
1. **My commute** (no account needed): home station, work station, usual morning and evening times, office days. Saved in the browser.
2. **Your week**: seven rows. Most say "Normal, ride as usual." An exception says what, when and one action, e.g. "Giants game: Embarcadero about 2× normal 9 to 10 PM. Your 6 PM ride is before the wave, no change needed." Each exception has **Add to calendar** (an .ics download, no server).
3. **This week on BART**: the unusual things anyone should know about, ranked by how far above normal they go. Clicking one flies the 3D map to that station and hour.
4. **Any station, any hour**: the existing planner, now the second layer.
5. **Proof** and **Limits**: kept. The hero says plainly that gate counts are station traffic, not train-car crowding.

### The exception rule (one function, used by the page and later by alerts)
`src/commute.js` takes the commute plus the week's data and returns exceptions:
- **Event overlap**: an event in `events.json` adds riders at the user's station within an hour of their usual time.
- **Unusual hour**: the user's station-hour is well above the same hour on ordinary weekdays (catches holiday surges without guessing).

Every exception traces back to `public/data/*.json`. Nothing is typed by hand.

## Sign-in (Firebase, from `handoff/auth/`)
The site fully works signed out. Signing in only adds sync across devices and, later, alerts.

| | Signed out | Signed in |
|---|---|---|
| My commute, favorites, recent lookups | This browser | Firestore `users/{uid}`, mirrored locally |
| Weekly alert email | None | Stretch goal |

- **Methods**: email and password, and Google (as in K3N0SU's `Account.tsx`).
- **Storage**: the handoff's `Profile` (`favorites`, `visits`, `searches`) plus one new field:
  ```
  commute: { home: "EMBR", work: "WCRK", morning: 8, evening: 17, officeDays: [1, 2, 4], alerts: false }
  ```
- **Rules**: unchanged `firestore.rules`. Each user can read and write only `users/{their uid}`.
- **Privacy**: stations are coarse on purpose. No names, addresses or location tracking. A "Delete my account and data" button.
- **Stack note**: the site is plain ES modules with no build step (there is no Node on the site machine). The handoff's React logic is ported to plain JS with the same Firestore shape, using the Firebase web SDK, so data stays compatible either way.
- **Config**: the six public Firebase web identifiers go in `public/config/firebase.json` (they are public IDs, not secrets; access is controlled by Auth and the rules). If the file is missing, sign-in is hidden and everything else works.

### What a person has to do in the Firebase console
1. Authentication: turn on Email/Password and Google.
2. Authentication > Authorized domains: add the Vercel domain and `localhost`.
3. Firestore: create the database, paste `handoff/auth/firestore.rules`.
4. Send the six web identifiers from Project settings > Your apps.

## Build order
| Step | What | Time |
|---|---|---|
| 1 | Read the new `events.json` and `days/*.json` shapes from K3N0SU's latest push | 15 min |
| 2 | Exception logic plus Your week, saved locally | 1 h |
| 3 | My commute setup flow (3 steps) | 40 min |
| 4 | New hero: Your week and This week on BART, map tours each event | 1 h |
| **Cut line: everything above works without accounts** | | |
| 5 | Firebase sign-in, sync, account panel, delete | 1 h |
| 6 | Alert preview (what this week's email would say); weekly email job as a stretch | 45 min |

## Testing
- Test accounts on localhost only; a demo account for judges plus the no-account path.
- Rules check: user A cannot read user B's document.
- Every number on the page spot-checked against the JSON.
- Desktop and phone, with the 3D map visible.

## Already built (in this push)
- `index.html`, `src/`: the site. Four hero versions (`?v=drive`, `daylight`, `cinema`, `split`) on a monochrome 3D map (MapLibre GL, OpenFreeMap tiles), crowd columns per station, trains moving on BART's timetable (`public/geo/trains.json`).
- `dev/serve.py`: local server, `python3 dev/serve.py`, then open http://127.0.0.1:5180. (The press-E studio editor was removed on Nov 21.)
- `agent/`: an earlier three-model event search (Claude orchestrates, Gemini searches, DeepSeek reasons). K3N0SU's `scripts/event_agent.py` is the one that feeds the site.

## Open questions
- Design: the site follows the Tesla monochrome direction the site owner asked for, not the serif and mono style in `DESIGN.md`.
- Deploy: `FRONTEND.md` now says Vercel. `dev/build_site.py` builds a static `dist/` that Vercel can serve as is.
- Direction-aware crowding (the commuter's own trip, e.g. Embarcadero to Walnut Creek) would need origin-destination shares: model work, K3N0SU's call.
