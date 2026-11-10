"""Phase 0 data spike -- ANALYZE step (offline; reads only the cached JSON).

Answers: Is LeagueDashLineups usable? Row caps? Do date filters behave?
What do lineup IDs look like? Can we reproduce possessions/ratings?
How big is the post-All-Star-break selection problem?

Usage:  .venv/bin/python scripts/phase0/analyze_spike.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RAW_DIR = Path("data/raw/phase0")
SEASONS = ["2022-23", "2023-24"]
WINDOWS = ["full", "pre_asb", "post_asb"]


def load(name: str) -> pd.DataFrame:
    rs = json.loads((RAW_DIR / f"{name}.json").read_text())["resultSets"][0]
    return pd.DataFrame(rs["rowSet"], columns=rs["headers"])


def load_team_windows() -> pd.DataFrame:
    frames = []
    for season in SEASONS:
        for path in sorted(RAW_DIR.glob(f"lineups_{season}_1610*_adv.json")):
            window = next(w for w in WINDOWS if path.stem.endswith(f"_{w}_adv"))
            df = load(path.stem)
            df["SEASON"], df["WINDOW"] = season, window
            df["N_ROWS_IN_RESPONSE"] = len(df)
            frames.append(df)
    return pd.concat(frames, ignore_index=True)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> None:
    df = load_team_windows()
    df["MIN_EXACT"] = df["SUM_TIME_PLAYED"] / 3000  # hypothesis: 5 players x deciseconds

    section("1. Row cap")
    for season in SEASONS:
        league = load(f"lineups_{season}_league_full_adv")
        team_full = df[(df.SEASON == season) & (df.WINDOW == "full")]
        print(f"{season}: league-wide rows={len(league)}, max L_RANK={league.L_RANK.max()}, "
              f"sum of per-team rows={len(team_full)}")
        print(f"  league-wide call min MIN={league.MIN.min()} (truncated by minutes?)")
    print("largest single per-team response:", df.N_ROWS_IN_RESPONSE.max(), "(cap is 2000)")

    section("2. Lineup identifiers")
    ids = df.GROUP_ID.str.strip("-").str.split("-")
    print("players per GROUP_ID:", ids.str.len().value_counts().to_dict())
    as_int = ids.apply(lambda xs: [int(x) for x in xs])
    print("IDs sorted numerically in every row:", bool(as_int.apply(lambda xs: xs == sorted(xs)).all()))
    print("IDs sorted as strings in every row:", bool(ids.apply(lambda xs: xs == sorted(xs)).all()))
    print("duplicate (season, window, team, GROUP_ID):",
          int(df.duplicated(["SEASON", "WINDOW", "TEAM_ID", "GROUP_ID"]).sum()))
    multi_team = df[df.WINDOW == "full"].groupby(["SEASON", "GROUP_ID"]).TEAM_ID.nunique()
    print("same 5 players listed under >1 team in a season:", int((multi_team > 1).sum()))

    section("3. Minutes: MIN vs SUM_TIME_PLAYED/3000")
    diff = (df.MIN - df.MIN_EXACT).abs()
    print(f"max |MIN - exact| = {diff.max():.3f}; share within 0.5 min: {(diff <= 0.5).mean():.4f}")
    print("MIN has decimals?", bool((df.MIN % 1 != 0).any()))

    section("4. Ratings internal consistency")
    nr = (df.OFF_RATING - df.DEF_RATING - df.NET_RATING).abs()
    print(f"|OFF-DEF-NET| max={nr.max():.2f}, share <=0.15: {(nr <= 0.15).mean():.4f}")
    print("nulls in key columns:", df[["POSS", "OFF_RATING", "DEF_RATING", "NET_RATING", "MIN"]].isna().sum().to_dict())
    print("rows with POSS == 0:", int((df.POSS == 0).sum()))
    extreme = df[df.NET_RATING.abs() > 100]
    print(f"rows with |NET_RATING| > 100: {len(extreme)}; their median POSS: {extreme.POSS.median()}")

    section("5. Date filtering: pre + post vs full")
    key = ["SEASON", "TEAM_ID", "GROUP_ID"]
    wide = df.pivot_table(index=key, columns="WINDOW", values=["POSS", "MIN_EXACT", "GP"],
                          aggfunc="sum", fill_value=0)
    for col in ["POSS", "MIN_EXACT", "GP"]:
        gap = wide[(col, "full")] - wide[(col, "pre_asb")] - wide[(col, "post_asb")]
        print(f"{col}: rows where full != pre+post (|gap|>0.01): {(gap.abs() > 0.01).sum()} of {len(gap)}; "
              f"max |gap|={gap.abs().max():.2f}")
    for season in SEASONS:
        s = df[df.SEASON == season]
        print(season, "total POSS by window:", s.groupby("WINDOW").POSS.sum().to_dict())

    section("6. Sample size distribution (lineup-windows)")
    for w in WINDOWS:
        p = df[df.WINDOW == w].POSS
        print(f"{w:9s} n={len(p):6d} median={p.median():5.0f}  >=50: {(p >= 50).sum():5d}  "
              f">=100: {(p >= 100).sum():4d}  >=200: {(p >= 200).sum():4d}")

    section("7. Counting stats: can we recompute POSS and ratings? (DEN 2023-24 full)")
    base = load("lineups_2023-24_1610612743_full_base")
    opp = load("lineups_2023-24_1610612743_full_opponent")
    adv = df[(df.SEASON == "2023-24") & (df.WINDOW == "full") & (df.TEAM_ID == 1610612743)]
    print("Base columns:", list(base.columns)[:40])
    print("Opponent columns:", [c for c in opp.columns if c.startswith("OPP_")][:30])
    m = adv.merge(base, on="GROUP_ID", suffixes=("", "_b")).merge(opp, on="GROUP_ID", suffixes=("", "_o"))
    m = m[m.POSS >= 50]
    m["POSS_EST"] = m.FGA + 0.44 * m.FTA - m.OREB + m.TOV
    m["OPP_POSS_EST"] = m.OPP_FGA + 0.44 * m.OPP_FTA - m.OPP_OREB + m.OPP_TOV
    m["ORTG_CALC"] = 100 * m.PTS / m.POSS
    m["DRTG_CALC"] = 100 * m.OPP_PTS / m.POSS
    m["PM_CHECK"] = m.PTS - m.OPP_PTS - m.PLUS_MINUS
    print(f"n lineups (>=50 poss) = {len(m)}")
    print(f"POSS_EST / POSS: median={np.median(m.POSS_EST / m.POSS):.3f}, "
          f"range=({(m.POSS_EST / m.POSS).min():.3f}, {(m.POSS_EST / m.POSS).max():.3f})")
    print(f"OPP_POSS_EST / POSS: median={np.median(m.OPP_POSS_EST / m.POSS):.3f}")
    print(f"|100*PTS/POSS - OFF_RATING| max={(m.ORTG_CALC - m.OFF_RATING).abs().max():.2f}")
    print(f"|100*OPP_PTS/POSS - DEF_RATING| max={(m.DRTG_CALC - m.DEF_RATING).abs().max():.2f}")
    print(f"PTS - OPP_PTS == PLUS_MINUS: {bool((m.PM_CHECK.abs() < 0.5).all())}")

    section("8. Selection into the post-All-Star-break target")
    rows = []
    for season in SEASONS:
        s = df[df.SEASON == season]
        pre = s[s.WINDOW == "pre_asb"].set_index(["TEAM_ID", "GROUP_ID"])
        post = s[s.WINDOW == "post_asb"].set_index(["TEAM_ID", "GROUP_ID"])
        # players who appeared for the team in ANY post-ASB lineup = still available to that team
        post_players = {(t, p) for (t, g) in post.index for p in g.strip("-").split("-")}
        pre = pre[pre.POSS >= 50].copy()
        pre["POST_POSS"] = post.POSS.reindex(pre.index).fillna(0)
        pre["ALL_5_AVAILABLE"] = [all((t, p) in post_players for p in g.strip("-").split("-"))
                                  for (t, g) in pre.index]
        pre["SEASON"] = season
        rows.append(pre.reset_index())
    sel = pd.concat(rows, ignore_index=True)
    sel["OBSERVED"] = sel.POST_POSS >= 50
    print(f"pre-ASB lineups with >=50 poss: {len(sel)}")
    print(f"  appear post-ASB at all: {(sel.POST_POSS > 0).mean():.3f}; with >=50 post poss: {sel.OBSERVED.mean():.3f}")
    print(f"  all 5 players still on team & playing post-ASB: {sel.ALL_5_AVAILABLE.mean():.3f}")
    print(f"  observed rate | all 5 available: {sel[sel.ALL_5_AVAILABLE].OBSERVED.mean():.3f}; "
          f"| not all available: {sel[~sel.ALL_5_AVAILABLE].OBSERVED.mean():.3f}")
    sel["PRE_NET_Q"] = pd.qcut(sel.NET_RATING, 5, labels=["Q1 worst", "Q2", "Q3", "Q4", "Q5 best"])
    sel["PRE_POSS_Q"] = pd.qcut(sel.POSS, 4, labels=["P1 fewest", "P2", "P3", "P4 most"])
    print("\nobserved rate by pre-ASB net-rating quintile:")
    print(sel.groupby("PRE_NET_Q", observed=True).agg(n=("OBSERVED", "size"), observed=("OBSERVED", "mean"),
                                                       median_pre_net=("NET_RATING", "median"),
                                                       median_pre_poss=("POSS", "median")).round(3))
    print("\nobserved rate by pre-ASB possessions quartile:")
    print(sel.groupby("PRE_POSS_Q", observed=True).agg(n=("OBSERVED", "size"), observed=("OBSERVED", "mean"),
                                                        median_pre_net=("NET_RATING", "median")).round(3))
    avail = sel[sel.ALL_5_AVAILABLE]
    print("\namong lineups whose 5 players were all available post-ASB, by pre-net quintile:")
    print(avail.groupby("PRE_NET_Q", observed=True).OBSERVED.agg(["size", "mean"]).round(3))

    section("9. Preliminary signal check (NOT a model result)")
    obs = sel[sel.OBSERVED].copy()
    post_all = df[df.WINDOW == "post_asb"].set_index(["SEASON", "TEAM_ID", "GROUP_ID"]).NET_RATING
    obs["POST_NET"] = post_all.reindex(pd.MultiIndex.from_frame(obs[["SEASON", "TEAM_ID", "GROUP_ID"]])).values
    r = np.corrcoef(obs.NET_RATING, obs.POST_NET)[0, 1]
    print(f"n={len(obs)} lineups with >=50 poss in both windows; corr(pre NET, post NET) = {r:.3f}")
    print(f"pre NET sd={obs.NET_RATING.std():.1f}, post NET sd={obs.POST_NET.std():.1f}")
    print(f"MAE of persistence (post=pre): {np.mean(np.abs(obs.POST_NET - obs.NET_RATING)):.2f}; "
          f"MAE of predicting 0: {np.mean(np.abs(obs.POST_NET)):.2f}; "
          f"MAE of in-sample post mean (optimistic, leaky): {np.mean(np.abs(obs.POST_NET - obs.POST_NET.mean())):.2f}")
    post_full = df[df.WINDOW == "post_asb"].set_index(["SEASON", "TEAM_ID", "GROUP_ID"])
    idx = pd.MultiIndex.from_frame(obs[["SEASON", "TEAM_ID", "GROUP_ID"]])
    for col in ["OFF_RATING", "DEF_RATING"]:
        print(f"corr(pre {col}, post {col}) = {bootstrap_corr(obs[col].values, post_full[col].reindex(idx).values)}")

    section("10. DEF_RATING denominator (DEN 2023-24, >=50 poss)")
    m["OPP_POSS_IMPLIED"] = 100 * m.OPP_PTS / m.DEF_RATING
    print(f"implied opp poss - POSS: median={np.median(m.OPP_POSS_IMPLIED - m.POSS):.2f}, "
          f"range=({(m.OPP_POSS_IMPLIED - m.POSS).min():.1f}, {(m.OPP_POSS_IMPLIED - m.POSS).max():.1f})")
    pace_calc = 48 * (m.POSS + m.OPP_POSS_IMPLIED) / 2 / m.MIN_EXACT
    print(f"|48*avg(POSS, OPP_POSS)/MIN - PACE| max={(pace_calc - m.PACE).abs().max():.2f}")

    section("11. Do PLAYER-level pre-ASB features carry more signal? (exploratory)")
    out = []
    for season in SEASONS:
        s = df[df.SEASON == season]
        pre = s[(s.WINDOW == "pre_asb") & (s.POSS > 0)].copy()
        pre["PLAYERS"] = pre.GROUP_ID.str.strip("-").str.split("-")
        long = pre.explode("PLAYERS")
        long["NET_X_POSS"] = long.NET_RATING * long.POSS
        prior = long.groupby(["TEAM_ID", "PLAYERS"]).agg(poss=("POSS", "sum"), nxp=("NET_X_POSS", "sum"))
        prior["on_net"] = prior.nxp / prior.poss  # possession-weighted on-court net rating
        team_pre = pre.assign(nxp=pre.NET_RATING * pre.POSS).groupby("TEAM_ID").agg(p=("POSS", "sum"), n=("nxp", "sum"))
        team_net = team_pre.n / team_pre.p
        post = s[(s.WINDOW == "post_asb") & (s.POSS >= 50)].copy()
        for _, row in post.iterrows():
            keys = [(row.TEAM_ID, p) for p in row.GROUP_ID.strip("-").split("-")]
            have = [k for k in keys if k in prior.index]
            out.append({"season": season, "post_net": row.NET_RATING, "post_poss": row.POSS,
                        "n_players_with_prior": len(have),
                        "player_prior": prior.loc[have, "on_net"].mean() if have else np.nan,
                        "team_pre_net": team_net.get(row.TEAM_ID, np.nan)})
    pl = pd.DataFrame(out)
    print(f"post-ASB lineups with >=50 poss: {len(pl)}; all 5 players have pre-ASB data for that team: "
          f"{(pl.n_players_with_prior == 5).mean():.3f}")
    c = pl[pl.n_players_with_prior == 5]
    print(f"n={len(c)}  corr(mean player pre on-court net, post lineup net) = {bootstrap_corr(c.player_prior.values, c.post_net.values)}")
    print(f"n={len(c)}  corr(team pre net, post lineup net)                = {bootstrap_corr(c.team_pre_net.values, c.post_net.values)}")


def bootstrap_corr(x: np.ndarray, y: np.ndarray, reps: int = 2000, seed: int = 0) -> str:
    """Pearson r with a 95% percentile bootstrap CI (resampling lineups)."""
    rng = np.random.default_rng(seed)
    n = len(x)
    boots = []
    for _ in range(reps):
        i = rng.integers(0, n, n)
        boots.append(np.corrcoef(x[i], y[i])[0, 1])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return f"{np.corrcoef(x, y)[0, 1]:.3f}  (95% CI {lo:.3f} to {hi:.3f})"


if __name__ == "__main__":
    pd.set_option("display.width", 140)
    main()
