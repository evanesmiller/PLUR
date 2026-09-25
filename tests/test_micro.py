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


def _run_corridor(n_agents: int, steps: int, seed: int = 0):
    """Agents cross a wall through a 4 m gap to an exit on the far side."""
    cell = 1.0
    occ = np.ones((40, 80), dtype=bool)
    occ[:, 40] = False
    occ[18:22, 40] = True
    dists, flows = distance_and_flow_fields(occ, cell, [(20, 70)])
    wd, wgx, wgy = wall_fields(occ, cell)
    rng = np.random.default_rng(seed)
    pos = np.column_stack([rng.uniform(2, 30, n_agents), rng.uniform(2, 38, n_agents)])
    vel = np.zeros_like(pos)
    status = np.ones(n_agents, dtype=np.int8)
    target = np.tile([70.5, 20.5], (n_agents, 1))
    flow_id = np.zeros(n_agents, dtype=np.int64)
    v0 = np.full(n_agents, 1.3)
    heading = np.zeros(n_agents)
    exit_flag = np.ones(n_agents, dtype=np.bool_)
    arrived = np.zeros(n_agents, dtype=np.bool_)
    params = PhysicsParams.for_scale(4.0, 0.1)
    hg = HashGrid(occ.shape, cell, params.cutoff, n_agents)
    max_speed = 0.0
    wall_violations = 0
    for _ in range(steps // 10):
        advance(
            10,
            pos,
            vel,
            status,
            target,
            flow_id,
            v0,
            heading,
            exit_flag,
            arrived,
            flows,
            dists,
            wd,
            wgx,
            wgy,
            occ,
            0.0,
            0.0,
            cell,
            hg.cell,
            hg.rows,
            hg.cols,
            hg.head,
            hg.nxt,
            hg.agent_cell,
            hg.forces,
            params.vector(),
        )
        on = status == 1
        max_speed = max(max_speed, float(np.hypot(*vel[on].T).max(initial=0.0)))
        wall_violations += int(
            (~occ[pos[on, 1].astype(int), pos[on, 0].astype(int)]).sum()
        )
    return status, pos, max_speed, wall_violations


def test_agents_pass_bottleneck_without_instability_or_wall_crossing():
    status, _, max_speed, violations = _run_corridor(150, 1500)
    assert violations == 0
    assert max_speed < 2.5 < MAX_SPEED  # nowhere near the numerical safety cap
    assert (status == 2).mean() > 0.9  # nearly everyone got through the gap and out


def test_kernel_is_deterministic():
    a = _run_corridor(80, 300, seed=3)
    b = _run_corridor(80, 300, seed=3)
    np.testing.assert_array_equal(a[1], b[1])
