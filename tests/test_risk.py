import numpy as np
from scipy.ndimage import gaussian_filter

from backend.sim.risk import PRESSURE_CRITICAL, RiskAccumulator


def _lattice(spacing: float, x0: float, x1: float, y0: float, y1: float) -> np.ndarray:
    xs = np.arange(x0 + spacing / 2, x1, spacing)
    ys = np.arange(y0 + spacing / 2, y1, spacing)
    gx, gy = np.meshgrid(xs, ys)
    return np.column_stack([gx.ravel(), gy.ravel()])


def _identity(x, y):
    return x, y


def test_splat_matches_gaussian_filter():
    rng = np.random.default_rng(1)
    occ = np.ones((60, 50), dtype=bool)
    acc = RiskAccumulator(occ, (0.0, 0.0), 2.0)
    pos = rng.uniform([0, 0], [100, 120], (800, 2))
    d, _ = acc.fields(pos, np.zeros_like(pos), 3.0)
    cnt = np.zeros(occ.shape)
    np.add.at(cnt, ((pos[:, 1] // 2).astype(int), (pos[:, 0] // 2).astype(int)), 1)
    ref = (
        gaussian_filter(cnt, 1.0, mode="constant", truncate=3.0)
        * 3.0
        / 4.0
        / acc._walk_norm
    )
    np.testing.assert_allclose(d, ref, atol=1e-12)


def test_uniform_crowd_reads_true_density_including_at_walls():
    occ = np.ones((50, 50), dtype=bool)
    acc = RiskAccumulator(occ, (0.0, 0.0), 1.0)
    pos = _lattice(1.0, 0, 50, 0, 50)  # one agent per m², 2.5 people each
    d, _ = acc.fields(pos, np.zeros_like(pos), 2.5)
    assert abs(d[25, 25] - 2.5) < 1e-6
    # normalised convolution: no fall-off to half at the edge
    assert abs(d[0, 25] - 2.5) < 1e-6


def test_pressure_zero_for_uniform_motion_and_high_for_counterflow():
    occ = np.ones((40, 40), dtype=bool)
    acc = RiskAccumulator(occ, (0.0, 0.0), 1.0)
    pos = _lattice(0.5, 0, 40, 0, 40)
    same = np.tile([1.0, 0.0], (len(pos), 1))
    _, p_same = acc.fields(pos, same, 1.0)
    counter = same.copy()
    counter[::2, 0] = -1.0
    _, p_counter = acc.fields(pos, counter, 1.0)
    assert p_same.max() < 1e-9
    assert p_counter[20, 20] > PRESSURE_CRITICAL


def test_hotspot_found_with_real_units():
    occ = np.ones((60, 60), dtype=bool)
    acc = RiskAccumulator(occ, (0.0, 0.0), 1.0)
    crowd = _lattice(0.4, 20, 30, 20, 30)  # 6.25 people/m² at scale 1
    acc.add(crowd, np.zeros_like(crowd), 1.0, t_min=1300.0, dt_min=1.0)
    res = acc.result(_identity)
    assert len(res.hotspots) == 1
    h = res.hotspots[0]
    assert 20 <= h["lon"] <= 30 and 20 <= h["lat"] <= 30
    assert h["peak_density"] >= 6.0 and h["t_peak_min"] == 1300.0
    assert res.red_exposure_person_min > 0


def test_calm_sparse_crowd_has_no_hotspots():
    occ = np.ones((60, 60), dtype=bool)
    acc = RiskAccumulator(occ, (0.0, 0.0), 1.0)
    pos = _lattice(1.0, 0, 60, 0, 60)  # 1 p/m²
    acc.add(pos, np.zeros_like(pos), 1.0, 0.0, 1.0)
    assert acc.result(_identity).hotspots == []
