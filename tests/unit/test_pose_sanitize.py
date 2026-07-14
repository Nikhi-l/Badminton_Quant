"""TASK-044 Slice A: identity/kinematic pose sanitation (plan §4, §11 fixtures).

The confirmed failure mode: a same-id, high-confidence joint teleport
x=0.10 → 0.90 → 0.12 was One-Euro-smoothed to 0.10 → 0.7645 → 0.317 — softened,
never rejected, contaminating the next frame. Rejection must run BEFORE
smoothing, be body-scale-relative, and never delete real athletic motion.
"""
import math

from app.pipeline.sanitize import sanitize_pose_track
from app.pipeline.smooth import smooth_pose_track

DT = 1.0 / 6.0   # production cadence


def _person(pid, cx, cy, h=0.5, kp_overrides=None, conf=0.9):
    """A person with bbox and 17 keypoints packed near the center; individual
    keypoints overridable as {index: (x, y)} or {index: (x, y, conf)}."""
    kps = []
    for i in range(17):
        x, y = cx + (i % 3 - 1) * 0.02, cy + (i // 3 - 2) * 0.03
        kps.append({"x": round(x, 5), "y": round(y, 5), "confidence": conf})
    for i, v in (kp_overrides or {}).items():
        kps[i] = {"x": v[0], "y": v[1],
                  "confidence": v[2] if len(v) > 2 else conf}
    return {"id": pid, "confidence": conf, "keypoints": kps,
            "bbox": {"x": cx, "y": cy, "w": h * 0.4, "h": h, "confidence": conf}}


def _track(people_per_frame):
    return [{"t": round(i * DT, 3), "people": people}
            for i, people in enumerate(people_per_frame)]


def _wrist(frame, pid=0):
    person = next(p for p in frame["people"] if p["id"] == pid)
    return person["keypoints"][9]


def test_high_conf_wrist_teleport_rejected_state_uncontaminated():
    """The audit repro: the false measurement becomes missing data AND the
    following true observations are accepted (no filter contamination)."""
    track = _track([
        [_person(0, 0.5, 0.6, kp_overrides={9: (0.10, 0.55)})],
        [_person(0, 0.5, 0.6, kp_overrides={9: (0.90, 0.55)})],   # teleport
        [_person(0, 0.5, 0.6, kp_overrides={9: (0.12, 0.55)})],
        [_person(0, 0.5, 0.6, kp_overrides={9: (0.13, 0.55)})],
    ])
    stats = {}
    sanitize_pose_track(track, stats)
    assert _wrist(track[1])["rejected"] is True
    assert _wrist(track[1])["confidence"] == 0.0
    assert "rejected" not in _wrist(track[2]) and _wrist(track[2])["confidence"] == 0.9
    assert "rejected" not in _wrist(track[3])
    assert stats["joint_rejects"] == 1 and stats["person_breaks"] == 0


def test_fast_smash_wrist_retained():
    """~2 frame-widths/s wrist (a real smash) stays observed."""
    xs = [0.50, 0.58, 0.72, 0.88]   # up to 0.16/sample ≈ 1 frame-width/s… + wind-up
    track = _track([[_person(0, 0.5, 0.6, kp_overrides={9: (x, 0.5)})] for x in xs])
    stats = {}
    sanitize_pose_track(track, stats)
    for f in track:
        assert "rejected" not in _wrist(f)
    assert stats["joint_rejects"] == 0


def test_whole_skeleton_teleport_marks_segment_not_rejection():
    """A same-id whole-person jump is an identity transition: nothing is
    rejected (a real player stands there) but the person starts a new seg."""
    track = _track([
        [_person(0, 0.20, 0.70)],
        [_person(0, 0.80, 0.30)],   # different human inherited the id
        [_person(0, 0.81, 0.31)],
    ])
    stats = {}
    sanitize_pose_track(track, stats)
    assert "seg" not in track[0]["people"][0]           # payload thrift
    assert track[1]["people"][0]["seg"] == 1
    assert track[2]["people"][0]["seg"] == 1            # stable after the break
    assert stats["person_breaks"] == 1
    # joints re-seed in the new segment: accepted immediately, not rejected
    assert all("rejected" not in kp for kp in track[1]["people"][0]["keypoints"])


def test_real_jump_and_lunge_retained():
    """Coherent whole-body motion within physical bounds never breaks a seg."""
    track = _track([
        [_person(0, 0.50, 0.70)],
        [_person(0, 0.56, 0.62)],   # jump: up + across, ~0.1 frame in 1/6s
        [_person(0, 0.62, 0.66)],
    ])
    stats = {}
    sanitize_pose_track(track, stats)
    assert all("seg" not in f["people"][0] for f in track)
    assert stats["person_breaks"] == 0


def test_gates_are_body_relative_far_player():
    """A displacement fine for a near player is a teleport for a far player."""
    jump = 0.30
    near = _track([
        [_person(0, 0.5, 0.7, h=0.5, kp_overrides={9: (0.40, 0.6)})],
        [_person(0, 0.5, 0.7, h=0.5, kp_overrides={9: (0.40 + jump, 0.6)})],
    ])
    far = _track([
        [_person(0, 0.5, 0.3, h=0.15, kp_overrides={9: (0.40, 0.25)})],
        [_person(0, 0.5, 0.3, h=0.15, kp_overrides={9: (0.40 + jump, 0.25)})],
    ])
    sanitize_pose_track(near)
    sanitize_pose_track(far)
    assert "rejected" not in _wrist(near[1])
    assert _wrist(far[1]).get("rejected") is True


def test_bone_surge_rejects_wrong_attachment():
    """A forearm suddenly 2x its rolling max length = wrist grabbed from
    someone else; velocity alone wouldn't catch it."""
    frames = []
    for _ in range(4):   # warm the bone stats (elbow 7 fixed, wrist 9 at 0.15)
        frames.append([_person(0, 0.5, 0.6,
                               kp_overrides={7: (0.50, 0.50), 9: (0.65, 0.50)})])
    frames.append([_person(0, 0.5, 0.6,
                           kp_overrides={7: (0.50, 0.50), 9: (0.95, 0.50)})])
    track = _track(frames)
    stats = {}
    sanitize_pose_track(track, stats)
    assert _wrist(track[4]).get("rejected") is True
    assert stats["bone_rejects"] == 1


def test_foreshortening_and_reextension_never_rejected():
    """2D bones legitimately shorten (overhead swing) and re-extend; only a
    surge PAST the rolling max is implausible."""
    wrist_x = [0.65, 0.65, 0.65, 0.55, 0.52, 0.65]   # extend→foreshorten→extend
    frames = [[_person(0, 0.5, 0.6, kp_overrides={7: (0.50, 0.50), 9: (x, 0.50)})]
              for x in wrist_x]
    track = _track(frames)
    stats = {}
    sanitize_pose_track(track, stats)
    assert stats["bone_rejects"] == 0
    assert all("rejected" not in _wrist(f) for f in track)


def test_persistent_relocation_reseeds_after_consecutive_rejections():
    """A far player's joint that GENUINELY relocated must not be rejected
    forever: after MAX_CONSEC_REJECT the state re-seeds."""
    frames = [[_person(0, 0.5, 0.3, h=0.15, kp_overrides={9: (0.10, 0.25)})]]
    for _ in range(5):
        frames.append([_person(0, 0.5, 0.3, h=0.15, kp_overrides={9: (0.90, 0.25)})])
    track = _track(frames)
    sanitize_pose_track(track)
    rejected = [bool(_wrist(f).get("rejected")) for f in track]
    assert rejected[1] and rejected[2] and rejected[3]   # three strikes…
    assert not rejected[4] and not rejected[5]           # …then accept reality


def test_low_confidence_keypoints_pass_through_untouched():
    track = _track([
        [_person(0, 0.5, 0.6, kp_overrides={9: (0.10, 0.55)})],
        [_person(0, 0.5, 0.6, kp_overrides={9: (0.90, 0.55, 0.05)})],  # < 0.15
        [_person(0, 0.5, 0.6, kp_overrides={9: (0.11, 0.55)})],
    ])
    sanitize_pose_track(track)
    kp = _wrist(track[1])
    assert "rejected" not in kp and kp["confidence"] == 0.05
    # and it never fed the state: the return to 0.11 is accepted
    assert "rejected" not in _wrist(track[2])


def test_long_gap_reenters_as_new_segment():
    track = [
        {"t": 0.0, "people": [_person(0, 0.3, 0.6)]},
        {"t": 2.0, "people": [_person(0, 0.6, 0.6)]},   # > 1.5s dropout
    ]
    stats = {}
    sanitize_pose_track(track, stats)
    assert track[1]["people"][0]["seg"] == 1
    assert stats["person_breaks"] == 0   # honest re-entry, not an id error


def test_smoothing_never_bridges_a_segment_break():
    """Integration with One-Euro: fresh filters per (id, seg) mean the first
    post-break sample renders AT its observation, not dragged toward the
    previous person."""
    track = _track([
        [_person(0, 0.20, 0.70)],
        [_person(0, 0.21, 0.70)],
        [_person(0, 0.80, 0.30)],   # identity transition
    ])
    sanitize_pose_track(track)
    assert track[2]["people"][0]["seg"] == 1
    smooth_pose_track(track)
    kp = track[2]["people"][0]["keypoints"][9]
    # the wrist of the new person is exactly where it was observed
    assert math.isclose(kp["x"], 0.80 + (9 % 3 - 1) * 0.02, abs_tol=1e-6)
