# Power BI (Phase 9)

This is a Power BI semantic model and a five-page report over the same validated warehouse and frozen model that serve Lineup Lab. Lineup Lab is the product; the Power BI report is the self-serve BI layer.

Everything here is generated from code, so it can be reproduced:

- the SQL star schema;
- the dataset export;
- the semantic model (tables, relationships, 65 DAX measures);
- the report pages.

Every key number is reconciled against PostgreSQL and the Phase 4 and Phase 6 results.

The model, measure and page reference is in [docs/powerbi_reference.md](powerbi_reference.md), which is generated.

## What exists, and what needs Power BI

| Deliverable | Status |
|---|---|
| SQL star schema (`sql/powerbi/bi_views.sql`, schema `bi`) | Built and applied |
| Dataset export: CSVs and an Excel workbook (`data/powerbi/`, git-ignored) | Built |
| Frozen-model predictions table (50,153 lineups, scored from pre-break data only) | Built |
| Semantic model as a Power BI Project: TMDL tables, CSV partitions, 12 relationships, 65 measures | Generated (`powerbi/LineupLab.SemanticModel/`) |
| Report: five pages, 62 visuals, slicers, titles, theme | Generated (`powerbi/LineupLab.Report/`); validated against Microsoft's PBIR JSON schemas |
| One-paste DAX script for the browser (`powerbi/measures.dax`) | Generated |
| Theme (`powerbi/LineupLab.theme.json`) | Generated |
| Validation: 116 automated tests | Passing |
| **Opening the project in Power BI and checking that it renders** | **Not done. Needs Power BI (see below).** |
| **Screenshots of the real report** | **Not available.** [`reports/phase9/wireframes/`](../reports/phase9/wireframes) has *layout wireframes* drawn from the specification; they are labelled as such and contain no data. |

**What I could not run.** Power BI's engines don't run on macOS, and no Power BI account was available to this project. The following were therefore never executed in Power BI:

- DAX evaluation;
- the TMDL parse;
- visual rendering.

**What was checked statically instead:**

- Every report file validates against Microsoft's published schemas.
- Every DAX reference resolves to a real table, column or measure.
- The measure graph has no cycles.
- The relationship graph has no ambiguous paths.
- Every measure's logic, re-implemented in pandas, reproduces the warehouse and the Phase 6 held-out evaluation exactly.

Even so, the first time you open the project, expect possible small fixes: a visual property, or the theme's base-theme name.

## Choosing a workflow on a Mac

| Option | Works on macOS? | What you can do | Needs |
|---|---|---|---|
| **A. Power BI Service in the browser** (recommended) | Yes (Safari, Chrome or Edge) | Create a semantic model from the Excel workbook, edit relationships and measures in the browser, build and share reports | A **work or school** Microsoft account. Personal accounts (gmail.com, outlook.com and similar) can't sign up. A university account, or a free Microsoft 365 developer or trial tenant, works. |
| **B. Power BI Desktop on Windows** | No. Desktop is Windows-only. | Open `powerbi/LineupLab.pbip` directly: model, measures and pages load, with data from the CSVs | A Windows PC (a university lab is fine), a cloud Windows VM, or Windows 11 ARM in Parallels on Apple Silicon |
| C. Fabric Git integration | Browser | Sync `powerbi/` from GitHub into a Fabric workspace | A Fabric capacity or trial. The CSV source would also need moving to OneDrive or SharePoint. Advanced; not set up here. |

The browser can't reach the local PostgreSQL without an on-premises data gateway, and that gateway is Windows-only. That's why the browser route uses the exported Excel workbook.

## Build the dataset (macOS, any route)

```bash
docker compose up -d                                       # PostgreSQL with the warehouse
.venv/bin/pip install -e ".[dev]"
.venv/bin/python scripts/phase9/export_powerbi.py          # ~35 s; applies sql/powerbi/bi_views.sql, then exports
.venv/bin/python scripts/phase9/build_powerbi_project.py   # regenerates powerbi/ and docs/powerbi_reference.md
.venv/bin/python -m pytest tests/powerbi                   # structure + reconciliation (116 tests)
```

Output in `data/powerbi/`:
- `csv/*.csv`: one file per table, plus `_Measures.csv`.
- `LineupLab_dataset.xlsx`: about 29 MB. Every table is a named Excel *table* (Power BI imports tables, not sheets).
- `manifest.json`: row counts, SHA-256 of each file, and the model artifact hash.

The data is NBA.com-derived, so it stays git-ignored, and you should keep any published report private. Don't use *Publish to web*.

## Route A: Power BI Service in the browser (macOS)

**One-time setup.** Sign in at https://app.powerbi.com with a work or school account. Create a workspace, or use *My workspace*.

**Data.**

1. Upload `data/powerbi/LineupLab_dataset.xlsx` to OneDrive for Business or SharePoint. A connection to OneDrive or SharePoint can be refreshed; a local-file import is a static copy.
2. In the workspace, choose **New item → Semantic model → Excel**, and pick the workbook. Microsoft's import experience has been changing; if your tenant shows a different path, see Microsoft's ["Get data from Excel workbook files"](https://learn.microsoft.com/power-bi/connect-data/service-excel-workbook-files).

**Model** (semantic model → **Open data model**; editing in the browser is generally available).

1. **Relationships.** Delete any relationships that were auto-detected. Then create the 12 listed in the [reference](powerbi_reference.md#relationships). All are many-to-one. Set *Cross-filter direction = Both* **only** on `bridge_lineup_player[lineup_id] → dim_lineup[lineup_id]`.
2. **Measures.** Open **DAX query view**, paste the whole of `powerbi/measures.dax`, choose **Run**, then **Update model with changes**. This adds all 65 measures to `_Measures`.
3. **Formatting.**
   - Set each measure's format string from the reference.
   - Hide the key and total columns marked *Hidden* in the reference.
   - Set *Sort by column* for `season_id`, `window_label`, `pre_sample_tier` and `pre_poss_bin`.
4. **Check.** Run this in DAX query view and compare with the validation table below:
   ```
   EVALUATE ROW("RMSE", CALCULATE([Model RMSE], dim_season[season_role] = "Held-out"))
   ```
   The result should be 24.2326.

**Report.**

1. Create a report on the semantic model.
2. Import the theme `powerbi/LineupLab.theme.json`.
3. Build the five pages as specified in the [reference](powerbi_reference.md#report-pages). Each visual's type, fields, title and position are listed; the [wireframes](../reports/phase9/wireframes) show the layout.
4. Save, then take your screenshots from the browser.

**Refresh.** Re-run `export_powerbi.py`, replace the workbook in OneDrive, and refresh the semantic model.

## Route B: Power BI Desktop on Windows

1. Copy the repository, or just `powerbi/` plus `data/powerbi/csv/`, to the Windows machine.
2. Open `powerbi/LineupLab.pbip` in Power BI Desktop (a 2025 or later release). If Desktop asks, enable *Power BI Project (.pbip) save option* and *Store reports using enhanced metadata format (PBIR)* under *Options → Preview features*.
3. Set the parameter: **Transform data → Edit parameters → DataFolder** = the folder holding the CSVs, ending with a backslash. The default is `C:\LineupLab\csv\`.
4. Choose **Refresh**. The model loads about 980k rows.
5. Check the report pages, then **File → Save**. Desktop writes the changes back into the project folder, so `git diff` shows them. Commit them, then re-run `pytest tests/powerbi`. The up-to-date test will flag the differences from the generator; update `model.py` or `report.py` if you want to keep them.
6. *Optional:* **File → Save as** `.pbix` for a single-file copy. Don't commit it: it embeds the data.
7. To publish, choose **Publish** in Desktop. This needs a work or school account.

A direct PostgreSQL connection is also possible from Windows, through Power Query's PostgreSQL connector against the `bi.*` views. The predictions and parameters tables still come from the CSVs, because they are computed in Python.

## Semantic model

```
dim_player 1─* bridge_lineup_player *─1 dim_lineup 1─* fact_lineup_window *─1 dim_season / dim_team / dim_window
                     (both directions ↔)            1─* fact_prediction    *─1 dim_season / dim_team
                                  fact_team_window *─1 dim_season / dim_team / dim_window
model_parameters (one row, constants)      _Measures (65 measures, 8 display folders)
```

- **Grain.**
  - `fact_lineup_window`: one lineup in one window (pre- or post-break).
  - `fact_team_window`: one team, season and window (games, wins, losses from game logs).
  - `fact_prediction`: one lineup that played after the break, scored by the frozen model.
- **Ratings are measures, never stored.** The ratings follow the analytical contract:
  - ORtg = DIVIDE(Σ pts, Σ poss) × 100.
  - DRtg divides Σ opponent points by Σ **opponent** possessions. 162 tiny lineup-windows with unknown opponent possessions are excluded from the numerator, exactly as in `v_lineup_window_ratings`.
  - Net is blank unless both ratings exist.
  - Team ratings come from summed **lineup** totals, so every rating shares one possession definition.
- **Player filters without double counting.**
  - A player filter flows from `dim_player` through `bridge_lineup_player` to a *set* of lineups, then to the facts. Each lineup's totals are summed once, however many selected players it contains.
  - A naive join counts such a lineup once per selected player. For Edwards + McDaniels (2025-26, pre-break) that gives 7,349 possessions instead of 5,104.
  - Multi-select therefore means *contains any*. For *contains all*, add the measure `All Selected Players In Lineup = 1` as a visual-level filter.
- **One filter path.** `dim_lineup` has no relationship to season or team; the facts carry those keys. The only bidirectional relationship is the bridge. A test enumerates the filter paths and asserts that no dimension reaches a fact two ways.
- **The frozen model is untouched.**
  - Predictions come from the API's `FrozenPredictor`. It refuses to run unless the artifact matches the committed freeze, and it reads only pre-break tables.
  - The observed post-break rating is joined afterwards, as the outcome column only.
  - Nothing is fitted, tuned or written.

## Measures

The measures fall into eight folders:

1. **Volume.**
2. **Ratings:** ORtg, DRtg, Net; possession-weighted lineup average; plus an *unweighted, misleading* average kept to demonstrate the bias.
3. **Pre vs Post:** each rating pre and post, and the changes.
4. **Reliability:**
   - Net Rating SE = √(K·(1/poss + 1/opp_poss)), and its 95% interval;
   - change SE, and a flag for a change larger than noise;
   - reliability τ²/(τ² + K·h);
   - lineups and share of possessions above 100 possessions;
   - lineup spread vs pure-noise spread.
5. **Team:** games, W–L, win %, record.
6. **Model:** these use the evaluation sample (≥ 25 post-break possessions per end), weighted by post-break possessions, exactly as Phase 6.
   - RMSE and MAE for the model, the team prior and the league mean;
   - model − team prior; skill vs the team prior;
   - R², noise-floor RMSE and R² ceiling;
   - mean predicted and mean observed (calibration).
7. **Selection:** population, continuing and appearing lineups; continuation and appearance rates; pre-break net of lineups that continued vs those that were dropped.
8. **Filters:** the all-selected-players flag.

The full DAX, with a description and format string for each measure, is in the [reference](powerbi_reference.md#measures-65).

## Report pages

| Page | Answers | Main visuals |
|---|---|---|
| 1 Team Overview | Which teams are good, and did that hold after the break? | KPI cards; net pre vs post by team; ORtg vs DRtg scatter; team table with records; net by season |
| 2 Lineup Analysis | Which lineups, with which players, and how sure are we? | Player search slicer; sample-size slicer; ranked lineup table with SE and reliability; possessions vs net scatter |
| 3 Statistical Reliability | How much of a lineup rating is noise? | Lineups and possessions by sample tier; observed spread vs noise spread; unweighted vs weighted averages; SE vs possessions |
| 4 Model Performance | Does the model beat simple baselines? | RMSE cards; RMSE by season vs baselines and the noise floor; calibration by decile; predicted vs observed; limitations |
| 5 Selection Bias | Which lineups survive the break? | Continuation and appearance rates; continuation by possession bin and by season; pre-break net of continued vs dropped lineups |

Every page has season slicers, plus team, window, player and evaluation-set slicers where they apply. Every visual has a readable title. The theme uses Lineup Lab's colors.

## Validation

Automated tests in `tests/powerbi/`: 116, all passing.

| Check | Result |
|---|---|
| Committed project = fresh generation from `model.py` / `report.py`; generation deterministic | Pass |
| All 71 report JSON files validate against Microsoft's PBIR schemas (vendored, MIT) | Pass |
| Every report field and DAX reference resolves; measures acyclic; parentheses balanced | Pass |
| Exactly one filter path from each dimension to each fact; only the bridge is bidirectional | Pass |
| Columns and types match the model; keys unique; no orphan keys; 5 players per lineup; row counts = warehouse | Pass |
| Team ORtg, DRtg and net for all **480** team-season-windows = `v_team_window_ratings` | Equal to 1e-9 |
| Net rating for all **143,172** lineup-windows = `v_lineup_window_ratings`, blank exactly where undefined | Equal to 1e-9 |
| Season totals (possessions, points, minutes); W–L = game logs | Equal |
| Player filter = distinct lineups (not the naive join); all-players semantics = SQL `HAVING count = n` | Equal |
| Per-lineup reliability measure = the frozen model's reliability (400 lineups) | Equal to 1e-9 |
| Held-out metrics, 2024-25 / 2025-26 / pooled: model, team-prior and league-mean RMSE and MAE; R²; noise floor; R² ceiling; skill | Equal to `holdout_findings.json` at 4 decimals (pooled RMSE **24.2326**, team prior 24.3081, noise floor 22.2721, R² 0.0699, n = 1,369) |
| Selection: population **8,120**, continuation 10.10%, appearance 28.99%, all five possession bins | Equal to Phase 4 `findings.json` |
| Documented prediction (lineup 281112): +5.894, team prior +6.113, observed +0.067 | Equal |
| Excel workbook: every table present as a named Excel table with the right row count | Pass |

**Limits of this validation.** The pandas reference implementations mirror the DAX line by line, with the model's filter propagation. They prove the *definitions* and the *data*. They cannot prove that the DAX engine evaluates each expression as intended. The first check in Power BI is the `[Model RMSE] = 24.2326` query above, then a few page totals against the validation table.

## Presenting this in interviews

**One sentence.** *"I built a star-schema semantic model in Power BI over a PostgreSQL warehouse of NBA lineup data, with 65 DAX measures that I reconciled to the source database and to my ML model's held-out evaluation, to the fourth decimal place."*

**Talking points (about two minutes each).**

1. **Modeling the grain.**
   - A lineup has five players, so it's a many-to-many relationship. I used a bridge table with a single bidirectional relationship, so a player filter selects a *set* of lineups.
   - A naive join would have inflated possessions by 44% for two teammates. I have a test that proves the model doesn't.
2. **Ratios done right.**
   - Ratings are aggregated first, then divided, with offense and defense using different denominators.
   - Averaging lineup ratings gives −8.1 for the 2025-26 league where the true pooled value is +0.2, because small samples dominate a simple mean. I keep that "misleading" measure in the model on purpose, to show the bias.
3. **Uncertainty in BI.**
   - Every rating can carry a standard error, a 95% interval and a reliability.
   - The reliability page shows that most lineups play too few possessions for their ratings to mean much. That's a sample-size story most dashboards hide.
4. **Honest model evaluation.**
   - The model page compares the frozen model with two baselines and with a noise floor.
   - The honest result is that it beats the league average but ties a simple team-strength baseline. I report that instead of hiding it.
5. **Selection bias.**
   - Only 10% of pre-break lineups keep playing after the break, and the ones that survive played more and looked better.
   - So post-break results are a selected sample. That's why the predictions are conditional.
6. **Engineering.**
   - The semantic model and report are code (TMDL and PBIR in Git), generated from one definition and validated against Microsoft's schemas.
   - The SQL views are versioned and the exports reproducible, with 116 automated tests.
   - I worked around macOS limits deliberately: Excel and the Service in the browser, or the PBIP on Windows.

**Likely questions, short answers.**

- *Why not average ratings?* Ratings are ratios. Their average weights a 10-possession lineup like a 1,000-possession one. You sum points and possessions, then divide.
- *Why a bridge table, and why bidirectional only there?* It resolves many-to-many. Bidirectional everywhere creates ambiguous paths and slow, surprising filters.
- *How do you know the numbers are right?* Every measure is reconciled against SQL views and the Python evaluation, automatically. The held-out RMSE matches to four decimals.
- *What would you do next?*
  - Incremental refresh from PostgreSQL through a gateway.
  - Row-level security per team, if this were a product.
  - Field parameters to switch metrics on a single chart.
