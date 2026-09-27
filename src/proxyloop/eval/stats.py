"""Statistics (EVAL §8): Wilson intervals and a cluster percentile bootstrap.

Pure Python with an explicit seeded RNG: the same inputs and seed give the
same interval. Clusters are episodes or instances; resampling whole clusters
keeps their internal correlation (EVAL §7 latency, §8.4).
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence

Z95 = 1.959963984540054  # the 97.5 % normal quantile


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """The Wilson score interval for ``k`` successes of ``n``."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"wilson needs 0 <= k <= n and n > 0, got k={k}, n={n}")
    phat, z2 = k / n, z * z
    centre = (phat + z2 / (2 * n)) / (1 + z2 / n)
    half = z / (1 + z2 / n) * math.sqrt(phat * (1 - phat) / n + z2 / (4 * n * n))
    return max(0.0, centre - half), min(1.0, centre + half)


def quantile(xs: Sequence[float], q: float) -> float:
    """The ``q`` quantile by linear interpolation (numpy's default)."""
    if not xs or not 0 <= q <= 1:
        raise ValueError("quantile needs values and 0 <= q <= 1")
    s = sorted(xs)
    pos = q * (len(s) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def cluster_bootstrap[T](
    clusters: Sequence[Sequence[T]],
    stat: Callable[[list[T]], float],
    *,
    seed: int,
    resamples: int = 10_000,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """A percentile CI for ``stat`` over the pooled items of ``clusters``,
    resampling whole clusters with replacement."""
    if not clusters:
        raise ValueError("the bootstrap needs at least one cluster")
    rng = random.Random(seed)
    n = len(clusters)
    draws = [
        stat([x for _ in range(n) for x in clusters[rng.randrange(n)]])
        for _ in range(resamples)
    ]
    return quantile(draws, alpha / 2), quantile(draws, 1 - alpha / 2)
