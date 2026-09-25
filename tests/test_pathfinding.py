import numpy as np

from backend.sim.pathfinding import WalkableSnapper, distance_and_flow_fields


def test_open_field_distance_and_flow_point_at_target():
    occ = np.ones((40, 40), dtype=bool)
    dist, flow = distance_and_flow_fields(occ, 1.0, [(20, 20)])
    d, f = dist[0], flow[0]
    assert d[20, 20] == 0
    assert d[20, 30] > d[20, 25] > 0
    assert f[20, 30, 0] < -0.9  # east of target: flow points -x
    assert f[5, 20, 1] > 0.9  # south of target (lower row = lower y): flow points +y


def test_walls_force_detour_and_block_unreachable():
    occ = np.ones((30, 30), dtype=bool)
    occ[:, 15] = False
    occ[10:20, 15] = True  # gap in the wall
    occ[0:5, 25:30] = False
    occ[1:4, 26:29] = True  # sealed pocket
    dist, flow = distance_and_flow_fields(occ, 1.0, [(2, 5)])
    d = dist[0]
    assert np.isinf(d[2, 27]) and np.all(flow[0][2, 27] == 0)
    assert d[2, 22] > 30  # 17 m as the crow flies, but the route goes through the gap


def test_no_corner_cutting_between_diagonal_obstacles():
    occ = np.ones((3, 3), dtype=bool)
    occ[0, 1] = False
    occ[1, 0] = False
    occ[2, :] = False
    occ[:, 2] = False
    dist, _ = distance_and_flow_fields(occ, 1.0, [(0, 0)])
    assert np.isinf(dist[0][1, 1])


def test_fields_are_cached_and_order_independent():
    occ = np.ones((25, 25), dtype=bool)
    a, _ = distance_and_flow_fields(occ, 1.0, [(3, 3), (20, 20)])
    b, _ = distance_and_flow_fields(occ, 1.0, [(20, 20), (3, 3)])
    np.testing.assert_array_equal(a[0], b[1])


def test_snapper_moves_blocked_points_only():
    occ = np.ones((10, 10), dtype=bool)
    occ[:, :5] = False
    s = WalkableSnapper(occ, (0.0, 0.0), 1.0)
    out = s.snap(np.array([[2.2, 4.5], [7.3, 4.5]]))
    assert out[0, 0] == 5.5  # moved to the first walkable column centre
    assert tuple(out[1]) == (7.3, 4.5)  # already walkable: unchanged
