# Project log: what worked, what didn't

Newest entries at the bottom. Times are Saturday Nov 21.

## Data sources

| Source | Status | Detail |
|---|---|---|
| CalEnviroScreen 5.0 tracts (shapes, population, poverty) | Works | 378 tracts in Alameda County, 241 in Contra Costa. No key. |
| FDIC bank branches | Works | 232 branches in Alameda, 178 in Contra Costa. No key. |
| Credit unions (OpenStreetMap) | Works | 70 found by name. FDIC does not list credit unions, so we add these. |
| Libraries and post offices (OpenStreetMap) | Works | 209 libraries, 275 post offices. These are the candidate sites. |
| BART stations (OpenStreetMap) | Works | 44 station entries, some are duplicates of one station and need merging. |
| Supermarkets and pharmacies (OpenStreetMap) | Works | 498 and 181. Backup services if the bank gap is small. |
| Check cashers and payday lenders (OpenStreetMap) | Too thin | About 30 lenders and 13 pawnbrokers for two counties. Not enough to draw conclusions from. Dropped from the analysis. |
| Census API (api.census.gov) | Failed | Now needs a key. We use CalEnviroScreen's poverty and population numbers instead. |
| OEHHA website | Failed | Blocks scripts. The same data is on data.ca.gov. |
| Bus stops (OpenStreetMap) | Not checked yet | The count query timed out twice. Not needed for the main result. |
| NCUA credit union branch file | Not checked yet | Would be a better credit union list than OpenStreetMap. |

## Decisions

- **09:45** First idea: map the distance from each neighborhood to banks and check cashers. Problem: check casher data is too thin (see table).
- **10:00** Read the rubric. Method (25) and validation (20) are almost half the score, and ties are broken on validation. A map of a gap is not enough.
- **10:05** New direction: measure the gap, then recommend where to put new service points and measure how much the gap shrinks. One headline number, before and after.
- **10:05** Check cashers stay out of the analysis. The fee calculator uses the legal fee cap instead (to be verified).

## Mistakes and fixes

- Overpass (the OpenStreetMap query server) rate-limits fast repeated queries. Fix: one combined query, saved to a local cache so we only download once.
- Started writing code before reading the rubric. Stopped and planned first.

## Open risks

- Tract centres are a rough stand-in for where people live. We say this as a limit.
- Walking time is estimated from straight-line distance. The Google Maps spot-check will tell us how far off it is.
- The improvement number is a projection from a model, not something measured in the real world.
- If the bank gap turns out small (decision at 11:30), we switch to the service with the biggest gap.

## Later decisions (10:10 to 10:35)

- **10:12** Tested an illegal dumping forecast for Oakland on 248,445 real reports. A machine-learning model reached 17.7% of next week's reports in the top 2% of grid squares. Random squares reach 2.0%, but a plain "worst squares of the past year" list already reaches 16.5%. Too small a gain to build a project on. Dropped.
- **10:14** Listed 15 candidate projects and compared the top three on how cleanly each could be tested.
- **10:18** Chose BART crowding. Found that BART's 2026 hourly file is empty (20 bytes). 2019 to 2025 are complete, and monthly totals exist through October 2026. Plan adjusted: test on 2025, scale the live forecast with 2026 monthly totals, and say so.
- **10:30** Final design: two layers. A trained model for the everyday hourly pattern, and a Gemini search agent that finds upcoming events. A rule-based harness joins them. The AI never produces a ridership number; numbers come from the model and from uplift measured on past games.

## Data sources for the final plan

| Source | Status | Detail |
|---|---|---|
| BART hourly origin-destination, 2019 to 2025 | Works | 21 to 38 MB per year, no header row |
| BART hourly, 2026 | Empty | File exists but has no data |
| BART monthly station totals, 2026 | Works | Through October 2026 |
| MLB schedule (past Giants and A's home games) | Not checked yet | First thing to check |
| Gemini with web search | Not checked yet | Depends on what our key allows |
