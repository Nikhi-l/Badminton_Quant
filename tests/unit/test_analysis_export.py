"""TASK-039: analysis.json builders — the machine-readable match report.

The export must label dead time explicitly (no_play is data, not absence),
carry per-rally markers (hits, shuttle-flight windows, audio peaks), and
project player ground contacts into court meters (ankles preferred, box foot
fallback) using the same court module production uses.
"""
from app.pipeline import analysis, court


def test_timeline_labels_no_play_explicitly():
    all_rallies = [
        {"start": 5.0, "end": 15.0, "dur": 10.0, "intensity": 4, "note": "long rally"},
        {"start": 30.0, "end": 40.0, "dur": 10.0, "intensity": 2, "note": "short"},
    ]
    selected = [{"src_start": 30.0, "start": 30.0, "end": 40.0, "dur": 10.0}]

    tl = analysis.timeline_segments(all_rallies, selected, duration=60.0)

    assert [s["kind"] for s in tl] == ["no_play", "rally", "no_play", "rally", "no_play"]
    assert [s["in_reel"] for s in tl if s["kind"] == "rally"] == [False, True]
    dead = sum(s["dur"] for s in tl if s["kind"] == "no_play")
    assert abs(dead - 40.0) < 0.01          # 0–5, 15–30, 40–60


def test_flight_segments_split_on_gaps_and_ignore_distrusted():
    pts = [{"t": i / 30, "x": 0.5, "y": 0.5, "confidence": 0.9} for i in range(60)]      # 0–2 s
    pts += [{"t": 3.0 + i / 30, "x": 0.5, "y": 0.5, "confidence": 0.9} for i in range(30)]  # 3–4 s
    pts += [{"t": 10.0, "x": 0.9, "y": 0.1, "confidence": 0.1}]   # distrusted point

    segs = analysis.flight_segments(pts)

    assert len(segs) == 2
    assert abs(segs[0]["start"]) < 0.05 and abs(segs[0]["end"] - 59 / 30) < 0.05
    assert abs(segs[1]["start"] - 3.0) < 0.05


def test_rally_hits_only_from_accepted_3d():
    ok = {"status": "ok", "shots": [
        {"t0": 12.1, "speed_kmh": 140.2, "speed_at_net_kmh": 96.0},
        {"t0": 13.4, "speed_kmh": 60.5},
    ]}
    hits = analysis.rally_hits(ok)
    assert [h["t"] for h in hits] == [12.1, 13.4]
    assert hits[0]["speed_at_net_kmh"] == 96.0 and "speed_at_net_kmh" not in hits[1]
    assert analysis.rally_hits({"status": "no_court"}) == []
    assert analysis.rally_hits(None) == []


def _homography():
    # A plausible fixed-camera court quad (far pair high, near pair low+wide).
    corners = [(0.30, 0.30), (0.70, 0.30), (0.90, 0.90), (0.10, 0.90)]
    return court.solve_homography(corners, court.COURT_PLANE)


def test_court_movement_prefers_ankles_and_projects_to_meters():
    hgr = _homography()
    players_track = [{"t": 1.0, "boxes": [
        {"id": 0, "x": 0.5, "y": 0.75, "w": 0.1, "h": 0.3, "confidence": 0.8},
        {"id": 1, "x": 0.5, "y": 0.35, "w": 0.05, "h": 0.12, "confidence": 0.7},
    ]}]
    pose_track = [{"t": 1.0, "people": [
        {"id": 0, "keypoints": (
            [{"x": 0.5, "y": 0.5, "confidence": 0.9}] * 15
            + [{"x": 0.49, "y": 0.9, "confidence": 0.9},   # left ankle
               {"x": 0.51, "y": 0.9, "confidence": 0.9}]   # right ankle
        )},
    ]}]

    series = analysis.court_movement(players_track, pose_track, hgr)

    assert set(series) == {"0", "1"}
    p0, p1 = series["0"][0], series["1"][0]
    assert p0["src"] == "ankles" and p1["src"] == "box_foot"
    # Near-baseline center foot lands inside the court, deep on the near half.
    assert 0.0 <= p0["x"] <= court.COURT_WIDTH_M
    assert court.COURT_LENGTH_M / 2 < p0["y"] <= court.COURT_LENGTH_M + 1.0
    # Far player projects to the far half.
    assert p1["y"] < court.COURT_LENGTH_M / 2
    assert analysis.court_movement(players_track, pose_track, None) == {}


def test_build_analysis_assembles_report():
    hgr = _homography()
    shuttle = [{"t": 30.5 + i / 30, "x": 0.5, "y": 0.5, "confidence": 0.9} for i in range(90)]
    result = {
        "duration": 60.0,
        "sport": "badminton",
        "n_rallies_found": 2,
        "all_rallies": [
            {"start": 5.0, "end": 15.0, "dur": 10.0, "intensity": 4},
            {"start": 30.0, "end": 40.0, "dur": 10.0, "intensity": 3},
        ],
        "rallies": [{
            "start": 30.0, "end": 40.0, "dur": 10.0, "src_start": 30.0,
            "intensity": 3, "note": "smash finish",
            "vision": {"shuttle": shuttle, "shuttle_quality": 0.9},
            "rally_3d": {"status": "ok", "shots": [
                {"t0": 31.0, "speed_kmh": 150.0, "speed_at_net_kmh": 101.0}]},
        }],
        "audio": {"status": "ok", "hop_s": 0.25, "series": [[0.0, -40.0]],
                  "peaks": [{"t": 31.05, "db": -9.0, "prominence_db": 25.0},
                            {"t": 55.0, "db": -20.0, "prominence_db": 12.0}]},
        "court": {"status": "ok", "source": "manual", "homography": hgr},
    }
    tracks = [{"players_track": [{"t": 31.0, "boxes": [
        {"id": 0, "x": 0.5, "y": 0.7, "w": 0.1, "h": 0.3, "confidence": 0.8}]}],
        "pose_track": []}]

    out = analysis.build_analysis(result, job_id="job1", per_rally_tracks=tracks,
                                  generated_at="2026-07-12T00:00:00Z")

    assert out["schema"] == "baddy.analysis.v1" and out["job_id"] == "job1"
    assert out["summary"]["rallies_found"] == 2 and out["summary"]["rallies_in_reel"] == 1
    assert out["court"]["calibrated"] is True
    r = out["rallies"][0]
    assert r["markers"]["hits"][0]["speed_at_net_kmh"] == 101.0
    assert len(r["markers"]["shuttle_flight"]) == 1
    # Only the peak inside (±1 s of) this rally window attaches to it.
    assert [p["t"] for p in r["markers"]["audio_peaks"]] == [31.05]
    assert r["players_court_m"]["0"][0]["src"] == "box_foot"
    kinds = [s["kind"] for s in out["timeline"]]
    assert "no_play" in kinds and kinds.count("rally") == 2
