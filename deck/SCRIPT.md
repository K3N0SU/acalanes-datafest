# Rushover: speaking script

Acalanes Data Fest 2026. K3N0SU and InterstellarApx. Target: 4 minutes. Estimate at 150 words per minute.

| # | Slide | Target | Words | Est. time | Running |
|---|---|---|---|---|---|
| 1 | Rushover | 10s | 26 | 0:10 | 0:10 |
| 2 | BART pays for every car it runs, full or empty. | 22s | 52 | 0:21 | 0:31 |
| 3 | A forecasting ensemble, and an agent harness for the days it cannot know. | 15s | 35 | 0:14 | 0:45 |
| 4 | Five forecasters, blended. Neural networks carry 60% of it. | 12s | 26 | 0:10 | 0:56 |
| 5 | On a year it never saw, it beats every simple method. | 9s | 21 | 0:08 | 1:04 |
| 6 | Same crowding standard, fewer cars. | 45s | 106 | 0:42 | 1:46 |
| 7 | The days a timetable cannot know. | 17s | 39 | 0:16 | 2:02 |
| 8 | Most of what we tried did not work. That is the finding. | 19s | 43 | 0:17 | 2:19 |
| 9 | Four honest limits, and what comes next. | 12s | 28 | 0:11 | 2:30 |
| 10 | Every technique here comes from published work. | 0s | 10 | 0:04 | 2:34 |
| | **Total** | 161s | 560 | **3:44** | 0:16 under against 4:00 |

## 1. Rushover
Target 10s, 26 words, about 0:10. Running total 0:10 of 4:00.

We're Rushover. BART pays for every train car it runs, full or empty. We built a model that tells BART how many cars each hour needs.

## 2. BART pays for every car it runs, full or empty.
Target 22s, 52 words, about 0:21. Running total 0:31 of 4:00.

BART has a money problem. Fares cover only 23 percent of operating costs, and the 2027 gap is about 375 million dollars. So our question: how many cars does each hour need? We used every BART trip from 2021 through 2025: 222 million, at 50 stations, joined to weather and 757 games.

## 3. A forecasting ensemble, and an agent harness for the days it cannot know.
Target 15s, 35 words, about 0:14. Running total 0:45 of 4:00.

We built two things. A forecast for every station and hour. And agents that find next week's games and concerts, with code that opens every source page. No language model ever writes a rider number.

## 4. Five forecasters, blended. Neural networks carry 60% of it.
Target 12s, 26 words, about 0:10. Running total 0:56 of 4:00.

The forecast blends five models: neural networks, including a transformer, gradient-boosted trees, and similar-day matching. Every choice was made on 2024, and 2025 was scored once.

## 5. On a year it never saw, it beats every simple method.
Target 9s, 21 words, about 0:08. Running total 1:04 of 4:00.

On 2025, a year it never saw, last week's count is off by 20 percent. Our blend is off by 12.7.

## 6. Same crowding standard, fewer cars.
Target 45s, 106 words, about 0:42. Running total 1:46 of 4:00.

Here is what that is worth. BART plans cars as expected riders plus a safety margin. A worse forecast means a bigger margin. Our first answer failed: a good timetable tied our blend, because the blend was trained to be right on average. Running short costs more than running long. So we retrained on that cost. That model needs 5 to 8 percent fewer cars than the best timetable, and 10 to 12 percent fewer than a plain one. That is 2 to 6 million dollars a year in electricity alone. BART's own switch to shorter trains saved about 12 million. Same lever, set every day.

## 7. The days a timetable cannot know.
Target 17s, 39 words, about 0:16. Running total 2:02 of 4:00.

A timetable cannot know about next week's game. With the event layer, the busiest hour of a Giants game goes from 17 percent error to under 10. And the agents found the cause of 18 of 24 real surges.

## 8. Most of what we tried did not work. That is the finding.
Target 19s, 43 words, about 0:17. Running total 2:19 of 4:00.

Most of what we tried failed. Of 23 corrections, 20 did nothing. The search agent invented a page, so now our code opens every link. And we assumed nobody rides after midnight. Nine million trip rows said 31 percent of concert riders do.

## 9. Four honest limits, and what comes next.
Target 12s, 28 words, about 0:11. Running total 2:30 of 4:00.

Our limits: we see gate counts, not how full each train is, we only counted electricity, and there is no 2026 hourly data yet. Now, the tool itself.

## 10. Every technique here comes from published work.
Target 0s, 10 words, about 0:04. Running total 2:34 of 4:00.

Backup slide for questions. Not part of the five minutes.

## Website, 1 minute
Hengyi talks, Mohammed clicks. About 60 seconds.

Have the site open at the top in the browser: http://127.0.0.1:5180. The calculator is empty until you press Calculate. Switch from the slides with Alt+Tab.

**Do 1:** Show the top of the site. Leave All 50 stations, Tue Nov 24, 5 AM to 12 AM, 10 cars. Press Calculate.

Say: This is Rushover. A planner picks a day and a time range and presses Calculate. First, the riders we predict for every hour, and the room the model says to run.

**Do 2:** Click the "Cars to run" tab.

Say: Then the cars. Grey is what BART runs today, from its real timetable. Blue is what Rushover would run: the same 53 trains, with the length set by the model.

**Do 3:** Set From to 10 AM and To to 3 PM. Press Calculate, then click "Cars to run".

Say: Midday, BART has the same 53 trains out as at rush hour. Rushover says four and five-car trains are enough: about 800 fewer car-hours, around 15 thousand dollars of electricity that day, if today's trains run at their average length.

**Do 4:** Station: Downtown Berkeley. Day: Sat Nov 28. From 5 AM, To 12 AM. Press Calculate. Then click "Cars to run".

Say: And it is not only rush hours. Saturday, Cal plays Pittsburgh at 4:30. Riders at Downtown Berkeley peak at 3 PM, and again at 9 when the game lets out. Rushover asks for ten-car trains at 2 and 3 PM, and eight at 9.

**Do 5:** Click "Full program, station planner and download" and scroll to the bar chart.

Say: The whole day exports as a program. And this is the test behind it: every plan held to the same standard on 2025. Ours needs the least. Thank you.
