"""The engine as the calculator drives it while the phone is scanning (app/worker.py): one call of
process_pending(live=True) between two readings of the commands, a preview when one is due."""
import json

import numpy as np
import pytest

import reconstruction.engine as engine_module
from reconstruction.engine import Box, EngineConfig, SessionEngine
from reconstruction.stereo_depth import PairReport, StereoResult
from tests.helpers import write_session
from tests.synthetic import orbit_poses


@pytest.fixture(scope="module")
def session(tmp_path_factory):
    return write_session(tmp_path_factory.mktemp("live"), n=60)


def _frames(sdir, count):
    out = []
    for mp in sorted((sdir / "frames").glob("*.json"))[:count]:
        out.append((json.loads(mp.read_text()), mp.with_suffix(".jpg")))
    return out


def _engine(sdir, cfg=None, events=None, clock=None):
    sj = json.loads((sdir / "session.json").read_text())
    return SessionEngine(sdir, Box.from_json(sj["box"]), cfg or EngineConfig(), emit=(events.append if events is not None else None),
                         **({"clock": clock} if clock else {}))


def _slow_computer(eng, clock, seconds_per_view):
    """Every view costs `seconds_per_view` on the engine's clock; returns the list of views processed, in order."""
    done = []
    real = eng._process

    def timed(fid):
        out = real(fid)
        done.append(fid)
        clock["t"] += seconds_per_view
        return out

    eng._process = timed
    return done


def _calculator_until_idle(eng, max_passes=400):
    """What the calculator does when no command arrives: pass after pass, the last views fused with what is
    available, until no view is left to compute. Returns the number of passes."""
    passes = 0
    while any(r.status == "received" for r in eng.frames.values()):
        eng.process_pending(live=True)
        passes += 1
        assert passes < max_passes, "the engine never finishes its backlog"
    eng.flush()
    return passes


def test_a_box_revision_brings_every_view_back(session):
    """The app advises to raise the box when the dish is taller (pause, then 'Boîte'). The volume is then rebuilt
    from the stored views - but through the rule that keeps the live backlog short, all but the last 12 were put
    off until finishing: the preview came back nearly empty and the verdict fell to 'poor, sides missing'."""
    clock = {"t": 0.0}
    eng = _engine(session, clock=lambda: clock["t"])
    for meta, jpg in _frames(session, 40):          # one view per pass, as the calculator receives them
        clock["t"] = meta["timestamp_s"]
        eng.add_frame(meta, jpg, received_at=clock["t"])
        eng.process_pending(live=True)
    eng.flush()
    before = eng.snapshot()[0]
    n_before = len(eng.fusion.integrated_frames)
    assert n_before >= 38 and before["quality"]["level"] == "good", before["quality"]

    b = json.loads((session / "session.json").read_text())["box"]
    eng.set_box(Box.from_json(dict(b, size_m={"width": 0.28, "height": 0.10, "depth": 0.28}, revision=1)), reprocess=True)
    assert len(eng.fusion.integrated_frames) == 0          # nothing silently transformed
    done = _slow_computer(eng, clock, seconds_per_view=0.4)
    passes = _calculator_until_idle(eng)

    assert not [f for f, r in eng.frames.items() if r.status == "deferred"], "no view is put off until finishing by a box revision"
    assert len(eng.fusion.integrated_frames) >= n_before - 2, (len(eng.fusion.integrated_frames), n_before)
    after = eng.snapshot()[0]
    assert after["box_revision"] == 1 and after["box_size_m"][1] == pytest.approx(0.10)
    q = after["quality"]
    assert q["level"] == "good" and "sides_missing" not in q["issues"] and q["sides_seen"] == before["quality"]["sides_seen"], q
    # ... by small slices, so that the calculator still publishes previews and reads the commands meanwhile,
    # and starting with the most recent views (where the phone is now)
    assert passes >= 10, f"{len(done)} views recomputed in {passes} passes"
    assert done[:3] == [39, 38, 37], done[:6]


def test_a_box_revision_does_not_bring_back_a_view_with_lost_tracking(tmp_path):
    """A view taken while the phone had lost its position is set aside when it arrives. Rebuilding the volume
    after a box revision must not put it back in (it used to be recomputed like the others, and then finished)."""
    sdir = write_session(tmp_path, poses=orbit_poses(60)[:10])
    mp = sdir / "frames" / "000004.json"
    m = json.loads(mp.read_text())
    m["tracking"] = {"state": "limited", "reason": "excessive_motion"}
    mp.write_text(json.dumps(m))
    eng = _engine(sdir)
    for meta, jpg in _frames(sdir, 10):
        eng.add_frame(meta, jpg)
        eng.process_pending(live=False)
    eng.flush()
    assert eng.frames[4].status == "rejected" and eng.frames[4].reason == "tracking_not_normal"
    b = json.loads((sdir / "session.json").read_text())["box"]
    eng.set_box(Box.from_json(dict(b, revision=1)), reprocess=True)
    eng.process_pending(live=False)
    eng.flush()
    assert eng.frames[4].status == "rejected" and eng.frames[4].reason == "tracking_not_normal"
    assert 4 not in eng.fusion.integrated_frames and len(eng.fusion.integrated_frames) >= 6


def test_a_slow_computer_hands_back_between_views(session):
    """Ten views are waiting and each takes 0.4 s. The engine used to compute them all in one call (12 at most):
    several seconds without a preview and without reading 'Terminer'. It now hands back after about a second,
    the most recent views first; nothing is lost, the others follow in the next calls."""
    clock = {"t": 0.0}
    eng = _engine(session, clock=lambda: clock["t"])
    for meta, jpg in _frames(session, 10):
        eng.add_frame(meta, jpg, received_at=0.0)
    done = _slow_computer(eng, clock, seconds_per_view=0.4)
    eng.process_pending(live=True)
    assert done == [9, 8, 7], done
    assert sum(r.status == "received" for r in eng.frames.values()) == 7
    passes = 1 + _calculator_until_idle(eng)
    assert sorted(set(done)) == list(range(10)) and passes >= 4
    assert not [f for f, r in eng.frames.items() if r.status == "deferred"]
    assert len(eng.fusion.integrated_frames) >= 8
    # a fast computer is not slowed down: everything that waits is done in one call
    clock2 = {"t": 0.0}
    fast = _engine(session, clock=lambda: clock2["t"])
    for meta, jpg in _frames(session, 10):
        fast.add_frame(meta, jpg, received_at=0.0)
    done2 = _slow_computer(fast, clock2, seconds_per_view=0.05)
    fast.process_pending(live=True)
    assert sorted(done2) == list(range(10))


def test_the_backlog_rule_still_puts_off_the_oldest_views(session):
    """More than 12 views waiting: the oldest are kept for finishing as before, the newest are computed first."""
    clock = {"t": 0.0}
    eng = _engine(session, clock=lambda: clock["t"])
    for meta, jpg in _frames(session, 20):
        eng.add_frame(meta, jpg, received_at=0.0)
    done = _slow_computer(eng, clock, seconds_per_view=0.4)
    eng.process_pending(live=True)
    assert sorted(f for f, r in eng.frames.items() if r.status == "deferred") == list(range(8))
    assert done == [19, 18, 17]


def test_a_view_without_partner_is_left_alone_until_something_changes(tmp_path):
    """Two views far from each other cannot be paired. The calculator looks at its queue five times a second:
    each time both were examined again and each time an event went to the database and to the phone
    (100 events in 50 passes). Now one event each, and a new look only when a view arrives."""
    P = orbit_poses(60)
    sdir = write_session(tmp_path, poses=[P[0], P[20], P[1]])
    frames = _frames(sdir, 3)
    events = []
    eng = _engine(sdir, events=events)
    looks = []
    real = engine_module.select_partners

    def counting(ref_id, *a, **k):
        looks.append(ref_id)
        return real(ref_id, *a, **k)

    engine_module.select_partners, restore = counting, real
    try:
        for meta, jpg in frames[:2]:
            eng.add_frame(meta, jpg)
        for _ in range(50):
            eng.process_pending(live=True)
        waiting = [e for e in events if e["type"] == "frame" and e["status"] == "waiting_partner"]
        assert len(waiting) == 2 and {e["frame_id"] for e in waiting} == {0, 1}, len(waiting)
        assert all(e["reason"] == "no_partner_geometry_yet" for e in waiting)
        assert len(looks) == 2, f"partners were looked for {len(looks)} times"
        assert eng.frames[0].attempts == 0 and eng.frames[0].status == "waiting_partner"
        # a neighbour of the first view arrives: both waiting views are looked at again, the first one is computed
        eng.add_frame(*frames[2])
        eng.process_pending(live=True)
        assert eng.frames[0].status == "depth_ready" and eng.frames[1].status == "waiting_partner"
        assert len([e for e in events if e["type"] == "frame" and e["status"] == "waiting_partner"]) == 2
    finally:
        engine_module.select_partners = restore


def test_a_view_whose_pairs_failed_is_tried_with_other_partners(tmp_path, monkeypatch):
    """The same two pictures always give the same answer. A view whose pairs had failed was nevertheless tried
    again with the same partners, up to the limit, then rejected - also in finishing, where the 'second chance'
    saw exactly the same views. It is now offered the next best partners."""
    sdir = write_session(tmp_path, poses=orbit_poses(120)[:9])      # close views: each has several possible partners
    eng = _engine(sdir)
    for meta, jpg in _frames(sdir, 9):
        eng.add_frame(meta, jpg, received_at=0.0)
    first_choice = [g.other_id for g in engine_module.select_partners(4, eng._candidates(), eng.box.size_m, eng.cfg.max_partners, eng.cfg.limits)]
    assert len(first_choice) == 2
    asked = []
    real = engine_module.compute_pair_depth

    def stereo(ref, other, size_m, params):
        if ref.frame_id == 4:
            asked.append(other.frame_id)
            if other.frame_id in first_choice:      # these two pairs fail, whatever the number of attempts
                return StereoResult(PairReport(4, other.frame_id, "rejected", "pose_inconsistent"))
        return real(ref, other, size_m, params)

    monkeypatch.setattr(engine_module, "compute_pair_depth", stereo)
    eng.process_pending(live=False)
    assert eng.frames[4].status == "waiting_partner" and eng.frames[4].reason == "pose_inconsistent"
    assert asked == first_choice
    eng.process_pending(live=False)               # the second chance of the finishing step
    second = asked[2:]
    assert second and not set(second) & set(first_choice), f"asked again for the same partners: {second}"
    assert eng.frames[4].status == "depth_ready"
    eng.flush()
    assert 4 in eng.fusion.integrated_frames
    assert eng.frames[4].attempts == 2
