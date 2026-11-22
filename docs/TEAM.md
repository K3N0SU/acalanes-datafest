# Team workflow

Repo: https://github.com/K3N0SU/acalanes-datafest

## Setup (teammate, before 10:00)
```sh
git clone https://github.com/K3N0SU/acalanes-datafest.git
cd acalanes-datafest
npm ci          # once package.json lands
npm run dev     # local site at http://localhost:5173
```
You need Node 20+ and Git. Python 3.11+ with pandas is useful for data cleaning.

## Rules so we don't step on each other
- **One owner per folder.** Only edit files you own (see the split below). If you need a change in someone else's area, tell them.
- `git pull --rebase` before you start and before every push. Push small, every 30–45 minutes.
- Data goes in `public/data/` as clean CSV/JSON. Raw downloads go in `data/raw/` and are not committed if they're bigger than 20 MB.
- Every dataset gets a line in `docs/SOURCES.md`: name, URL, date pulled, and what we used it for.
- Never commit API keys or `.env` files.

## Split
See "Who does what" in [PROJECT.md](PROJECT.md).

## Checkpoints
See the build order in [PROJECT.md](PROJECT.md).
