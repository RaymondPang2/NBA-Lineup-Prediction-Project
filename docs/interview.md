# Lineup Lab in 60 seconds

A spoken explanation of about 150 words, about one minute. Every number in it comes from the frozen evaluation (`GET /api/v1/model/performance`).

> "Lineup Lab analyzes every five-player lineup in the NBA. In basketball, coaches choose which five players share the floor, and the question I wanted to answer is: which combinations actually work, and what should we expect from them next?
>
> I built the full pipeline myself. It pulls eight seasons of lineup data from NBA.com, validates it, and loads it into PostgreSQL with data-quality checks that roll back a bad load. On top of that sit a FastAPI service and a React dashboard where you can rank lineups and make predictions.
>
> For the machine-learning part, I predicted a lineup's net rating after the All-Star break using only pre-break data. I validated chronologically and froze the model before testing it once on two held-out seasons.
>
> The honest result is that it clearly beat a league-average baseline (RMSE 24.23 versus 25.15), but it was not significantly better than a simple team-strength baseline (24.31). Most of the variation is small-sample noise. So the product shows every prediction with its uncertainty and that baseline, rather than overstating it."

## Likely follow-up questions

**Why does it only tie the team baseline?**
A lineup's post-break rating is measured over a few dozen to a few hundred possessions, so most of its variation is luck. Even a perfect model would miss by about 22.3 points of RMSE (the noise floor); the model's error is 24.2. Once you know how good the team is, very little lineup-specific signal is left. I treated that as a finding, not something to hide.

**How did you prevent data leakage?**
- Features come only from pre-break data; post-break results are used only as labels.
- Cross-validation was chronological: always train on earlier seasons.
- The held-out seasons were locked behind a key that the code only issues after the model file is frozen, hashed and committed to git.
- Tests check that the feature queries never read post-break rows.

**Why linear regression?**
I compared linear regression, ridge and random forest with nested cross-validation, using a rule fixed in advance: pick the simplest model within one standard error of the best. Linear regression had the lowest error (21.73, against about 21.80) and was the simplest, and its coefficients are easy to explain.

**What was the hardest engineering problem?**
The NBA stats API silently cuts responses off at 2,000 rows, so I request each team separately and reject any response that hits the cap. I also recovered exact opponent possessions from the published pace numbers, so that defensive ratings reconcile with NBA.com's to the decimal.

**What would you do next?**
Use play-by-play data to adjust for opponent quality and garbage time, which is the main source of the remaining noise, and re-run the audit of provisional current-season predictions as the season progresses.

**Is it deployed?**
No. It runs locally, with a daily refresh scheduled through macOS launchd. NBA.com's terms allow private, non-commercial use, but not a public, regularly updated statistics database without consent, so I kept it local.
