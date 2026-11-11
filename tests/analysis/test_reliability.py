"""The measurement model is tested on SIMULATED lineups with known true values, so we can check that
the estimators recover the truth before trusting them on real data."""
import numpy as np
import pandas as pd
import pytest

from nba_lineups.analysis import reliability as rel

TAU, MU = 6.0, -1.0                     # true SD and mean of lineup net rating
POINTS = np.array([0, 1, 2, 3])         # discrete, skewed points per possession (not normal)
PROBS = np.array([0.50, 0.04, 0.34, 0.12])
SIGMA2 = float(PROBS @ POINTS**2 - (PROBS @ POINTS) ** 2)   # true per-possession variance
K_TRUE = 100**2 * SIGMA2


def simulate(n=20000, seed=1, split=False, log_mean=3.3):
    """Lineups with lognormal possession counts; each possession's points drawn from PROBS.

    split=True: also return two disjoint halves of each lineup's possessions (like home/road games)."""
    rng = np.random.default_rng(seed)
    poss = np.maximum(rng.lognormal(log_mean, 1.0, n).astype(int), 4)
    opp = np.maximum(poss + rng.integers(-2, 3, n), 4)
    theta = rng.normal(MU, TAU, n)
    mean_pts = PROBS @ POINTS

    def rating(m, shift):   # mean points over m possessions, true mean shifted by theta/200 per end
        counts = np.array([rng.multinomial(mi, PROBS) for mi in m])
        return 100 * (counts @ POINTS) / m + shift

    if not split:
        x = rating(poss, theta / 2) - rating(opp, -theta / 2)   # both ends share the base rate
        return x, rel.sampling_h(poss, opp), theta, poss
    pa, oa = poss // 2, opp // 2
    pb, ob = poss - pa, opp - oa
    xa = rating(pa, theta / 2) - rating(oa, -theta / 2)
    xb = rating(pb, theta / 2) - rating(ob, -theta / 2)
    return xa, rel.sampling_h(pa, oa), xb, rel.sampling_h(pb, ob), theta


@pytest.fixture(scope="module")
def sim():
    return simulate()


def test_sampling_h_undefined_without_possessions():
    h = rel.sampling_h([10, 0, 5], [10, 4, 0])
    assert h[0] == pytest.approx(0.2) and np.isnan(h[1]) and np.isnan(h[2])


def test_method_of_moments_recovers_true_components(sim):
    x, h, _, _ = sim
    vc = rel.fit_variance_components(x, h)
    assert vc.tau2 == pytest.approx(TAU**2, rel=0.2)    # tau^2 is the hard part: most lineups are tiny
    assert vc.k == pytest.approx(K_TRUE, rel=0.05)
    assert vc.mu == pytest.approx(MU, abs=0.3)
    assert vc.sigma_per_possession == pytest.approx(np.sqrt(SIGMA2), rel=0.03)


def test_reliability_properties():
    vc = rel.VarianceComponents((0.0,), tau2=25.0, k=12000.0, n=100)
    r = vc.reliability_at([10, 100, 1000, 10000])
    assert np.all(np.diff(r) > 0) and np.all((r > 0) & (r < 1))      # rises with sample size, stays in (0,1)
    n50 = vc.possessions_for_reliability(0.5)
    assert n50 == pytest.approx(2 * 12000 / 25)
    assert vc.reliability_at(n50) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        vc.possessions_for_reliability(1.0)


def test_shrinkage_moves_toward_prior_more_for_small_samples():
    vc = rel.VarianceComponents((0.0,), tau2=25.0, k=12000.0, n=100)
    x = np.array([30.0, 30.0])
    h = rel.sampling_h([20, 2000], [20, 2000])
    post, sd = rel.shrink(x, h, prior_mean=0.0, vc=vc)
    assert 0 < post[0] < post[1] < 30                     # both shrunk; the small lineup much more
    assert np.all(sd < vc.standard_error(h))              # posterior is tighter than the raw SE
    assert np.all(sd < np.sqrt(vc.tau2))                  # ...and tighter than the prior


def test_shrinkage_reduces_error_on_simulated_lineups(sim):
    x, h, theta, _ = sim
    vc = rel.fit_variance_components(x, h)
    post, _ = rel.shrink(x, h, vc.mu, vc)
    assert np.mean((post - theta) ** 2) < 0.5 * np.mean((x - theta) ** 2)
    # calibration: regressing truth on the posterior mean gives slope ~1 (on the raw rating, slope << 1).
    # Tolerance reflects the sampling error of tau^2 itself (seeds give 0.97-1.20).
    assert np.polyfit(post, theta, 1)[0] == pytest.approx(1.0, abs=0.25)
    assert np.polyfit(x, theta, 1)[0] < 0.5


def test_interval_coverage_is_nominal(sim):
    x, h, theta, poss = sim
    vc = rel.fit_variance_components(x, h)
    big = poss >= 100                                     # normal approximation needs a decent sample
    lo, hi = rel.confidence_interval(x[big], h[big], vc)
    assert np.mean((theta[big] >= lo) & (theta[big] <= hi)) == pytest.approx(0.95, abs=0.02)
    post, sd = rel.shrink(x, h, vc.mu, vc)
    assert np.mean(np.abs(theta - post) <= rel.Z95 * sd) == pytest.approx(0.95, abs=0.02)


def test_split_half_identifies_tau2_and_k_without_the_sampling_model():
    # Larger lineups (median ~400 possessions) so the covariance itself is precise; with small halves its
    # standard error is ~ Var(x_a) / sqrt(n), which can exceed tau^2 (a lesson for the real data too).
    xa, ha, xb, hb, _ = simulate(n=15000, seed=2, split=True, log_mean=6.0)
    sh = rel.split_half(xa, ha, xb, hb)
    assert sh.cov == pytest.approx(TAU**2, rel=0.15)               # covariance of disjoint halves = tau^2
    assert sh.diff.k == pytest.approx(K_TRUE, rel=0.05)            # differences identify K
    vc = rel.VarianceComponents((MU,), TAU**2, K_TRUE, 0)
    assert sh.predicted_r(vc) == pytest.approx(sh.r, abs=0.03)     # the model predicts the observed r


def test_spearman_brown():
    assert rel.spearman_brown(0.5) == pytest.approx(2 / 3)
    assert rel.spearman_brown(0.0) == 0.0 and rel.spearman_brown(1.0) == 1.0


def test_cluster_bootstrap_brackets_the_estimate():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"g": np.repeat(np.arange(40), 25), "x": rng.normal(size=1000)})
    out = rel.cluster_bootstrap(df, "g", lambda d: {"mean": d.x.mean()}, n_boot=200)
    assert out.loc["mean", "lo"] < out.loc["mean", "estimate"] < out.loc["mean", "hi"]


def test_kish_effective_n():
    assert rel.kish_effective_n([1, 1, 1, 1]) == 4
    assert rel.kish_effective_n([1, 0, 0, 0]) == 1
