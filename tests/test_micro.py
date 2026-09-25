import numpy as np

from backend.sim.micro import (
    MASS,
    MAX_SPEED,
    STIFFNESS_SAFETY,
    HashGrid,
    PhysicsParams,
    advance,
    wall_fields,
)
from backend.sim.pathfinding import distance_and_flow_fields


def test_params_respect_stability_bound():
    for scale in (1.0, 5.0, 12.0, 30.0):
        for dt in (0.05, 0.1, 0.2):
            p = PhysicsParams.for_scale(scale, dt)
            assert p.a_social / p.b_social / MASS * dt**2 <= STIFFNESS_SAFETY + 1e-12
            assert p.k_body / MASS * dt**2 <= STIFFNESS_SAFETY + 1e-12
    # coarse agents are bigger so a packed crowd of agents has real areal density
    assert np.isclose(PhysicsParams.for_scale(16.0).radius, 1.0)


def _simulate(occ, pos, target_xy, target_rc, steps, scale=4.0, exit_flag=True):
    """Run the kernel with every agent heading for one target; returns final state
    plus the fastest speed seen and how often an agent stood in a wall cell."""
    cell = 1.0
    n = len(pos)
    dists, flows = distance_and_flow_fields(occ, cell, [target_rc])
    wd, wgx, wgy = wall_fields(occ, cell)
    pos = pos.astype(np.float64).copy()
    vel = np.zeros_like(pos)
    status = np.ones(n, dtype=np.int8)
    target = np.tile(target_xy, (n, 1)).astype(np.float64)
    arrived = np.zeros(n, dtype=np.bool_)
    params = PhysicsParams.for_scale(scale, 0.1)
    hg = HashGrid(occ.shape, cell, params.cutoff, n)
    max_speed = 0.0
    violations = 0
    for _ in range(steps // 10):
        advance(
            10, pos, vel, status, target, np.zeros(n, dtype=np.int64),
            np.full(n, 1.3), np.zeros(n), np.full(n, exit_flag), arrived,
            flows, dists, wd, wgx, wgy, occ, 0.0, 0.0, cell,
            hg.cell, hg.rows, hg.cols, hg.head, hg.nxt, hg.agent_cell, hg.forces,
            params.vector(),
        )  # fmt: skip
        max_speed = max(max_speed, float(np.hypot(*vel.T).max()))
        violations += int((~occ[pos[:, 1].astype(int), pos[:, 0].astype(int)]).sum())
    return pos, arrived, max_speed, violations, params


def _corridor(n_agents: int, steps: int, seed: int = 0):
    """Agents cross a wall through a 4 m gap to an exit on the far side."""
    occ = np.ones((40, 80), dtype=bool)
    occ[:, 40] = False
    occ[18:22, 40] = True
    rng = np.random.default_rng(seed)
    pos = np.column_stack([rng.uniform(2, 30, n_agents), rng.uniform(2, 38, n_agents)])
    return _simulate(occ, pos, [70.5, 20.5], (20, 70), steps)


def test_agents_pass_bottleneck_without_instability_or_wall_crossing():
    # exit-bound agents queue politely through the gap, so allow ~4 minutes
    _, arrived, max_speed, violations, _ = _corridor(150, 2400)
    assert violations == 0
    assert max_speed < 2.5 < MAX_SPEED  # nowhere near the numerical safety cap
    # everyone reaches the exit zone; the behaviour layer releases them from there
    assert arrived.mean() > 0.9


def test_kernel_is_deterministic():
    a = _corridor(80, 300, seed=3)
    b = _corridor(80, 300, seed=3)
    np.testing.assert_array_equal(a[0], b[0])


def test_pushing_crowd_cannot_exceed_physical_packing():
    """400 agents all driving at one point: spacing projection keeps the packed
    crowd below ~9.4 people/m² (Fruin's upper limit is about 10)."""
    occ = np.ones((80, 80), dtype=bool)
    rng = np.random.default_rng(1)
    pos = rng.uniform(5, 75, (400, 2))
    scale = 4.0
    final, _, max_speed, violations, params = _simulate(
        occ, pos, [40.5, 40.5], (40, 40), 1200, scale=scale, exit_flag=False
    )
    assert violations == 0 and max_speed < MAX_SPEED
    d = np.hypot(*(final[:, None, :] - final[None, :, :]).transpose(2, 0, 1))
    np.fill_diagonal(d, np.inf)
    # Jacobi projection leaves some residual overlap in the tightest spots
    assert d.min(axis=1).min() > 0.7 * params.min_spacing
    core = np.hypot(*(final - final.mean(axis=0)).T) < 4.0
    density = core.sum() * scale / (np.pi * 4.0**2)
    assert 4.0 < density < 10.0  # compressed, but physically possible
