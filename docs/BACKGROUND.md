# Background: what we actually built, in plain words

Read this before presenting. It is for us, so we can explain every part ourselves and answer follow-up questions. Judges are told to give credit for "the work and evidence the team can explain".

## 1. The one-paragraph version
We predict how many people go through the gates at each BART station in each hour. A trained model handles ordinary days. On top of it sit three smaller pieces: add-ons for conditions that repeat, a search layer that finds next week's events, and an AI reasoning layer that decides how each event should change the forecast. The AI never produces a rider count; it only adjusts curves we measured on real past events.

## 2. What kind of model is it?
**An ensemble of five forecasters, blended. Neural networks carry 60% of the weight, gradient-boosted trees 20%, similar-day matching 20%.** The live forecast on the site still runs on the trees; the blend is the best-scoring version on the 2025 test.

| Forecaster | 2025 error on its own | Weight in the final blend |
|---|---|---|
| Deep feed-forward network (3 random starts, averaged) | 12.9% | 20% |
| Gradient-boosted trees (two, averaged) | 13.1% | 20% |
| Network trained on the trees' leftover error (3 starts) | 13.1% | 10% |
| Small transformer | 13.7% | 30% |
| Similar-day matching (cosine similarity) | 14.9% | 20% |
| **All five blended** | **12.7%** (12.66%) | |

The blend beats every part because they make different mistakes. Against the trees alone it is better on ordinary days (12.6% to 12.2%) and on the busiest hours (11.1% to 10.4%), and slightly worse on weekends (18.4% to 18.7%). The weights were chosen on 2024, in steps of 0.1.

Things we learned building it:
- **Training each network three times from different random starts and averaging helped every time.**
- **Attention did not beat a plain deep network here.** A second, bigger transformer got zero weight; the plain network matched it and trained four times faster. The first transformer stays in because its mistakes differ from the others'.
- **For whole-system daily totals the trees alone are still best** (4.0% against 4.4% for the blend). The blend wins hour by hour, not on totals.
- **Reconciliation** (making hours add up to days) improved an earlier blend from 12.8% to 12.7% but added nothing to the final one, so it is not in it.

**The deep feed-forward network.** The simplest kind of neural network: layers of weighted sums with a bend between them, trained by backpropagation. It takes the same recent profiles as the transformer but treats them as one long list of numbers.

**The transformer.** A neural network built on "attention": for each thing it reads, it works out which of the other things matter most. Ours is tiny (two layers). For one station and direction it reads eight "tokens", the 24-hour profiles of the last eight same-weekday days, plus the weekday, month, holiday flag and weather, and outputs the 24 hours of the day being forecast. It trains in minutes on a laptop CPU.

**Similar-day matching.** For each station-day we build a list of numbers describing it (recent hourly shape, level, trend, weekday, season, holiday). Cosine similarity measures the angle between two such lists: the smaller the angle, the more alike the days. We take the 10 most alike past days for that station and average what happened on them. Computing all the similarities at once is a matrix multiplication.

**The trees.** The rest of this section.

- A **decision tree** asks a chain of yes/no questions ("Is it a weekday?" "Was this hour above 500 riders last week?") and ends at a number.
- **Boosting** builds hundreds of small trees one after another. Each new tree is trained on the mistakes the earlier trees still make. The final answer is all of them added up.
- We use scikit-learn's `HistGradientBoostingRegressor`, 700 trees each, and **average two versions**:
  - one trained with a **Poisson** objective, which suits counts (riders can't be negative, and busy hours vary more than quiet ones);
  - one trained to minimise **absolute error**, which is exactly what our error measure rewards.
  Averaging the two was better on 2024 than either alone (13.8% against 14.2% and 14.1%).

**Why are trees the base and not the neural network?** Our data is a table: one row per station-hour, 34 columns. On tables this size, boosted trees are usually as good as or better than neural networks, train in two minutes on a laptop, and need no GPU. We tested it: our transformer alone scored 13.7% against the trees' 13.1%.

**Two kinds of transformer in the project:** the small one above, which we trained ourselves on ridership, and the large language models in the search and reasoning layers (Gemini, DeepSeek, Claude), which we did not train. We call those, and we check what they say.

## 2b. Why do the trees beat the neural network on their own?
A judge may well ask this. Four reasons, all visible in our results:

1. **The best signals are already worked out.** The trees are handed 34 prepared inputs: the median of the same hour over 8 weeks, last year's value scaled to this year, the station's trend. A tree only has to split on them. The transformer sees eight raw daily profiles and has to discover those summaries itself.
2. **We have little data by deep-learning standards.** About 110,000 station-days. Neural networks need far more examples than trees to reach the same accuracy.
3. **The patterns are jagged, not smooth.** "If it is a holiday AND this station AND after 10 PM" is one split for a tree. A network has to bend a smooth function around every such corner.
4. **Training time.** The trees converge in two minutes. Our transformer trained for a few minutes on a laptop with no GPU; it did well on 2024 and slipped on 2025, a sign it had not settled.

This is a known result, not a quirk of ours: Grinsztajn et al. (NeurIPS 2022) show tree models still beating deep learning on tables of this kind. See [REFERENCES.md](REFERENCES.md).

**Then why keep the transformer?** Because it is wrong in different places. The trees lean on summaries; the transformer reads the whole shape of recent days. Averaging forecasts that make different mistakes cancels some of them: 13.1% and 13.7% alone, 12.8% together, 12.7% after reconciliation.

## 2c. Reward functions and reinforcement learning: what we can truthfully say
- **Every model here is trained against an objective**, which is the supervised-learning version of a reward: the trees minimise Poisson deviance and absolute error, the transformer minimises level-weighted absolute error by backpropagation.
- **We built and tested a reward-driven learner.** Each week it re-weights the forecasters; a forecaster's reward is minus its absolute error, and weights are updated multiplicatively (the Hedge algorithm, Freund and Schapire 1997). On 2024 it scored 12.98%; fixed weights scored 12.76%. We kept fixed weights.
- **Why it lost:** week-to-week differences between forecasters are mostly noise, so chasing last week's winner does not pay.
- **Why full reinforcement learning does not fit forecasting:** reinforcement learning is for decisions that change what happens next. A forecast does not change how many people ride. It would fit the next step, deciding what advice to give riders or where to send staff, where each choice has consequences you can reward.

Say "we tested reward-driven online weighting and it lost to a fixed blend". Do not say "we used reinforcement learning".

## 3. What does the model look at? (34 inputs)
| Group | Inputs | Why |
|---|---|---|
| Recent pattern | The same hour 1, 2, 3 and 4 weeks ago; the average, median and spread over 8 weeks; the hour before and after, last week | Next Tuesday at 8 AM looks most like recent Tuesdays at 8 AM |
| Trend | The station's and the system's last week against the 8 before; growth against the same weeks last year | Ridership is still recovering and drifts |
| Last year | The same weekday a year ago, scaled up to this year's level | Seasons and school terms |
| Calendar | Hour, weekday, month, week of year, holiday flags | |
| Weather | Rain this hour, last 3 hours, whole day; the day's high; wind | Rain removes riders |

The single most useful input is the **median of the same hour over the last 8 weeks**. A median ignores one-off spikes, so a game last week doesn't fool it.

Everything except weather is at least a week old, so the forecast really is a week ahead.

## 4. How we tested it, and why it matters
**Walk-forward validation**, also called time-ordered or out-of-time testing:

| Step | Trained on | Used for |
|---|---|---|
| Choose the setup | 2022 to 2023 | Every decision, scored on 2024 |
| Final score | 2022 to 2024 | 2025, scored **once** |

**Why not a random 80/20 split?** With time data a random split leaks the future. If Tuesday the 14th is in the test set and Tuesday the 21st is in training, the model has effectively seen next week. Our inputs include last week's counts, so the leak would be direct and the score would look far better than it is. Splitting by time is stricter and honest. (If asked: we did not use an 80/20 split, and this is why.)

**Error measure:** riders the forecast got wrong ÷ total riders, added over every station and hour. Statisticians call it WAPE (weighted absolute percentage error). We say "error".

## 5. What the numbers mean
| Number | Meaning |
|---|---|
| 13.1% | Our error on 2025, per station, direction and hour |
| 20.1% | The obvious method: copy the same hour from last week |
| 14.7% | The best method that needs no trees: a ridge regression (a weighted average of the same history) |
| 4.0% | Our error on the whole system's daily total |
| 10.5% | Our error per station and hour on ordinary days |

**Why not 5% per station-hour?** Two reasons we measured:
1. **Counting noise.** People arrive at random. Even if you knew the true average for a station-hour exactly, the actual count would jitter around it. For our data that jitter alone is about 4 points. Small stations are noisier than big ones.
2. **Hour-to-hour randomness.** We tested a method that cheats: it averages the same hour from the week before *and the week after*, and is told the true daily total. It scores 10.3%. Ours, given the same daily total, scores 8.7%. If a method that sees the future can't do better, most of what remains isn't knowable.

Adding the errors up over a whole day or the whole system makes the noise cancel, which is why those numbers are much lower.

## 6. The other three layers
**Add-ons ("accessories").** A calendar of one condition (Pride Sunday, a football Saturday) plus a correction learned from how wrong the main model was the last time that condition held. The rule: learn on 2023, apply to 2024, and switch it on only if 2024 improves. Then report on 2025. We tested 23; 3 passed. The rule exists to stop us keeping things that only looked good by chance.

**Event curves.** For every past Giants or A's game we took actual riders minus what the model expected, hour by hour around first pitch, and divided by attendance. That gives "extra riders per 1,000 fans" for each hour: a measured curve. Football got its own curve from Cal games.

**Search and feeds.** League schedule feeds (exact, no AI) cover sports. A search agent covers the rest. Any claim needs a source page, and our code opens the page; if it doesn't load, the claim is dropped.

**Reasoning ("the harness").** For an event with no curve of its own, three AI specialists each answer one narrow question (how big is the crowd, how do they get there, when do they arrive and leave). A lead model checks them and writes a plan: which measured venue this resembles, and a multiplier. Code applies it, inside limits (the multiplier must be between 0.3 and 3; no more than 45% of a crowd through one station; nobody on a train after midnight).

## 7. Terms we might be tempted to use, and the truth
Don't say these unless you can defend them. Here is what each one is and whether we used it.

| Term | What it means | Did we use it? | What to say instead |
|---|---|---|---|
| Transformer | A neural network built on attention; the design behind chatbots | **Yes.** A small one we trained, 30% of the final blend. Alone it loses to the trees. | "Five forecasters blended; neural networks carry 60%. The blend scores 12.7% against 13.1% for the trees alone." |
| Cosine similarity | Measuring the angle between two lists of numbers to see how alike two things are | **Yes**, for similar-day matching (20% of the blend) | "We find the 10 most alike past days for a station and use what happened on them." |
| Embeddings | Lists of numbers a neural network learns to describe something | Only the station embedding inside the transformer | Don't lead with it. |
| Matrix multiplication | The arithmetic inside neural networks, and how all the similarities are computed at once | Yes, inside the transformer and the similarity search | Only if asked how it runs fast. |
| Reinforcement learning, reward function | An agent learning by trial and reward | **Tested, not adopted.** We built an online learner that re-weights the forecasters every week, rewarded for low error (reward = minus the absolute error). It scored 12.98% on 2024 against 12.76% for the fixed blend, so we kept the fixed blend. Strictly this is online learning from a reward, not full reinforcement learning. | "We tried reward-driven online weighting. A fixed blend was better, so we used that." |
| 80/20 split | Random split into training and test rows | **No**, on purpose. | "We split by time, because a random split leaks the future." |
| Overfitting | A model memorising noise in the training data so it does worse on new data | **Yes, we hit it** (see below) | |
| Ensemble | Combining several models | Yes: two tree models averaged, then blended with the transformer and similar days | "We average two models trained with different objectives." |
| Hyperparameter tuning | Choosing settings like tree count and depth | Yes: on 2024 only | |
| Ablation | Removing one piece to see what it was worth | Yes | "Weather is worth 1.2 points on rainy days and nothing on dry ones." |
| Data leakage | Test information sneaking into training | We designed against it | See section 4 |
| Out-of-distribution | Asking a model about something unlike its training data | Yes: football with only baseball curves | "34% to 23.5% using reasoning alone." |
| Hallucination | A language model stating something false with confidence | We caught one | "It cited a page that returned 'not found'. Now we open every page." |

## 8. What went wrong (all real)
| What we tried | What happened | Why | Fix |
|---|---|---|---|
| A transformer on its own | 13.7% on 2025, worse than the trees (13.1%); it also did better on 2024 than 2025 | Trained for a few minutes, one seed; unstable | Blended with the trees and similar days: 12.8% |
| Reward-driven online weighting of forecasters | 12.98% on 2024, worse than a fixed blend (12.76%) | Week-to-week errors are mostly noise, so chasing last week's best forecaster does not pay | Fixed blend weights |
| Added 13 inputs to the first model | 2024 error rose from 14.5% to 14.7% | **Overfitting**: more inputs with the same small trees fit noise | Deeper, slower trees and averaging two models: 13.8% |
| A tourism index from airport stations | Worse overall (14.0% to 14.6%), worse even at tourist stations | The recent-weeks inputs already carry tourist seasons; the index added noise | Removed |
| Baseball's curve for football | 29% became 41% | **Wrong transfer**: far fewer football fans arrive by BART at that station | A curve measured on football: 19% |
| 23 add-ons | 20 did nothing or hurt (conventions, gas prices, daylight, air quality, most festivals) | The model already absorbs them from its own history | The 2024 rule keeps 3 |
| Our first source check | Threw out 14 of 15 correct answers | The search tool returns redirect links, so the addresses never matched | Open each page directly |
| Trusting a search result's link | One link was invented (page not found) | **Hallucination** | An event's link must open, or it is rejected |
| Holiday week forecast | Counted the holiday twice | We started from last year's Thanksgiving week and then applied the holiday cut again | Start from a plain week, apply the cut once |
| Paid web search | Credits ran out mid-run; three searches never finished | Long reasoning on every search call | League schedule feeds; 7 of 7 events matched |
| The 3 to 5% target per station-hour | Not reached: 10.5% | Counting noise and hour-to-hour randomness (section 5) | Reported honestly; reached at the system-day level (4.0%) |

## 9. One-line answers
- **What model?** "An ensemble of five: neural networks including a transformer, gradient-boosted trees, and similar-day retrieval. Blended, 12.7% error on a year it never saw."
- **How do you know it works?** "We scored it once on 2025, a year it never saw, against six simpler methods."
- **Did you tune on the test year?** "No. Every choice was made on 2024."
- **Where does AI come in?** "Finding events and reasoning about how they differ from ones we measured. It never writes a number."
- **How do you stop it making things up?** "Sources must open, a second pass checks dates, league feeds confirm sports, and code enforces limits."
- **Biggest weakness?** "No 2026 hourly data to check next week against, and measured curves for only two sports."
