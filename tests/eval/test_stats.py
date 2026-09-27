"""Wilson intervals and the cluster bootstrap, checked against known values and
a known distribution (coverage on simulated clustered data)."""

from __future__ import annotations

import random
from statistics import fmean as mean

import pytest

from proxyloop.eval.stats import cluster_bootstrap, quantile, wilson


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [
        (0, 10, 0.0, 0.2775),  # the zero-event bound
        (5, 10, 0.2366, 0.7634),
        (10, 10, 0.7225, 1.0),
        (81, 263, 0.2553, 0.3662),
    ],
)
def test_wilson_matches_published_values(k: int, n: int, lo: float, hi: float) -> None:
    got = wilson(k, n)
    assert got == pytest.approx((lo, hi), abs=5e-4)


def test_wilson_refuses_an_empty_or_impossible_count() -> None:
    for k, n in ((0, 0), (3, 2), (-1, 4)):
        with pytest.raises(ValueError):
            wilson(k, n)


def test_quantile_interpolates_linearly() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    assert quantile(xs, 0.5) == 2.5 and quantile(xs, 0.0) == 1.0
    assert quantile(xs, 1.0) == 4.0 and quantile(xs, 0.95) == pytest.approx(3.85)


def test_the_bootstrap_is_seeded() -> None:
    clusters = [[1.0, 2.0], [3.0], [4.0, 5.0, 6.0]]
    a = cluster_bootstrap(clusters, mean, seed=3, resamples=200)
    assert a == cluster_bootstrap(clusters, mean, seed=3, resamples=200)
    assert a != cluster_bootstrap(clusters, mean, seed=4, resamples=200)


def test_cluster_bootstrap_covers_the_true_mean_of_clustered_data() -> None:
    """Clusters share a N(0, 1) effect, items add N(0, 0.3) noise: the mean is
    0 and items within a cluster are strongly correlated. A 95 % interval
    must cover 0 in about 95 % of simulations; an item-level bootstrap would
    under-cover badly (checked below)."""

    rng = random.Random(20260926)
    sims, covered, naive_covered = 200, 0, 0
    for sim in range(sims):
        clusters: list[list[float]] = []
        for _ in range(30):
            effect = rng.gauss(0, 1)
            clusters.append([effect + rng.gauss(0, 0.3) for _ in range(4)])
        lo, hi = cluster_bootstrap(clusters, mean, seed=sim, resamples=300)
        covered += lo <= 0 <= hi
        items = [[x] for c in clusters for x in c]
        lo, hi = cluster_bootstrap(items, mean, seed=sim, resamples=300)
        naive_covered += lo <= 0 <= hi
    assert 0.90 <= covered / sims <= 0.99
    assert naive_covered / sims < 0.80  # ignoring the clusters is wrong here


def test_the_bootstrap_needs_clusters() -> None:
    with pytest.raises(ValueError):
        cluster_bootstrap([], mean, seed=0)
