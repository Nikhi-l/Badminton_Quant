"""TASK-034: Phase-0 bench metric math (scripts/bench/metrics.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.bench import metrics  # noqa: E402


def _track(n=30, dx=0.005):
    return [{"t": i / 30, "x": 0.3 + i * dx, "y": 0.5} for i in range(n)]


def test_shuttle_f1_perfect_and_shifted():
    gt = [{**p, "visible": True} for p in _track()]
    perfect = metrics.shuttle_f1(_track(), gt)
    assert perfect["f1"] == 1.0

    shifted = [{**p, "x": p["x"] + 30 / 512} for p in _track()]   # 30px off at 512 wide
    bad = metrics.shuttle_f1(shifted, gt)
    assert bad["f1"] == 0.0

    # Half the points missing → recall 0.5, precision 1.0.
    half = metrics.shuttle_f1(_track()[::2], gt)
    assert half["recall"] == 0.5 and half["precision"] == 1.0


def test_teleports_per_1000():
    clean = metrics.teleports_per_1000(_track())
    assert clean == 0.0
    spiky = _track()
    spiky[10] = {"t": 10 / 30, "x": 0.95, "y": 0.05}
    assert metrics.teleports_per_1000(spiky) > 50   # 2 impossible steps / 30 frames


def test_player_count_and_overcount():
    gt = [{"t": i / 6, "boxes": [{"id": "near", "x": 0.3, "y": 0.7},
                                 {"id": "far", "x": 0.6, "y": 0.3}]} for i in range(12)]
    pred_ok = [{"t": i / 6, "boxes": [{"id": 0, "x": 0.3, "y": 0.7},
                                      {"id": 1, "x": 0.6, "y": 0.3}]} for i in range(12)]
    m = metrics.player_count_metrics(pred_ok, gt)
    assert m["exact_count_frac"] == 1.0 and m["overcount_frac"] == 0.0

    pred_four = [{"t": f["t"], "boxes": f["boxes"] * 2} for f in pred_ok]
    m4 = metrics.player_count_metrics(pred_four, gt)
    assert m4["exact_count_frac"] == 0.0 and m4["overcount_frac"] == 1.0


def test_id_switches_counts_relabels():
    gt = [{"t": i / 6, "boxes": [{"id": "near", "x": 0.3, "y": 0.7}]} for i in range(12)]
    stable = [{"t": i / 6, "boxes": [{"id": 7, "x": 0.3, "y": 0.7}]} for i in range(12)]
    assert metrics.id_switches(stable, gt)["switches_per_track"] == 0.0

    churn = [{"t": i / 6, "boxes": [{"id": i, "x": 0.3, "y": 0.7}]} for i in range(12)]
    m = metrics.id_switches(churn, gt)
    assert m["switches_per_track"] == 11.0   # a fresh id every frame


def test_pose_pck_near_far_split():
    def person(cy, h, jitter=0.0):
        return {"bbox": {"x": 0.5, "y": cy, "h": h},
                "keypoints": [{"x": 0.5 + jitter, "y": cy}]}
    gt = [{"t": 0.0, "people": [person(0.7, 0.4), person(0.3, 0.15)]}]
    # near player exact, far player off by 0.02 (>5% of its 0.15 height)
    pred = [{"t": 0.0, "people": [person(0.7, 0.4), person(0.3, 0.15, jitter=0.02)]}]
    m = metrics.pose_pck(pred, gt)
    assert m["near"] == 1.0 and m["far"] == 0.0


def test_d3_health_and_labels():
    r3 = {"shots": [
        {"t0": 1.0, "speed_kmh": 90.0,
         "samples": [{"t": 1.0, "x": 2.0, "y": 10.0, "z": 2.0},
                     {"t": 1.5, "x": 2.0, "y": 12.0, "z": 0.1}]},
    ], "rejected": {"floor": 2}}
    h = metrics.d3_health(r3)
    assert h == {"accepted": 1, "below_floor_accepted": 0, "rejected": {"floor": 2}}

    labelled = metrics.d3_against_labels(r3, [
        {"t_hit": 1.05, "landing_xy_m": [2.0, 12.3], "speed_kmh": 100.0}])
    assert abs(labelled["landing_median_m"] - 0.3) < 1e-9
    assert abs(labelled["speed_mape"] - 0.1) < 1e-9


def test_release_gates_shape():
    # The runner iterates these keys; a rename must break loudly here.
    assert set(metrics.RELEASE_GATES) == {
        "shuttle_f1", "shuttle_teleports_per_1000", "player_exact_count_frac",
        "player_overcount_frac", "player_id_switches_per_track",
        "pose_pck05_near", "pose_pck05_far", "d3_below_floor_accepted",
        "d3_landing_median_m", "d3_speed_mape"}
