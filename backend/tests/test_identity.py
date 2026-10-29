from app.vision.identity import IdentityTracker

FRAME = (1280, 720)


def tracker(**kw):
    return IdentityTracker(entry_zone=(0.0, 0.5, 0.4, 1.0), **kw)


def test_new_track_in_entry_zone_gets_the_worker_id():
    t = tracker()
    t.request_handoff(4, "Ana", now=100)
    new, expired = t.update(101, [(1, (50, 400, 150, 700))], FRAME)
    assert new == [(1, 4, "Ana")] and not expired
    assert t.worker_for(1) == 4


def test_track_outside_entry_zone_is_not_assigned():
    t = tracker()
    t.request_handoff(4, "Ana", now=100)
    new, _ = t.update(101, [(1, (900, 400, 1000, 700))], FRAME)
    assert new == [] and t.worker_for(1) is None


def test_track_that_appeared_just_before_the_crossing_is_accepted():
    t = tracker()
    t.update(98, [(1, (50, 400, 150, 700))], FRAME)       # el track aparece antes del cruce
    t.request_handoff(4, "Ana", now=100)
    new, _ = t.update(100.1, [(1, (60, 400, 160, 700))], FRAME)
    assert new == [(1, 4, "Ana")]


def test_old_track_is_not_stolen_by_a_later_handoff():
    t = tracker()
    t.update(10, [(1, (50, 400, 150, 700))], FRAME)       # alguien llegó hace mucho
    t.request_handoff(4, "Ana", now=100)
    new, _ = t.update(101, [(1, (60, 400, 160, 700))], FRAME)
    assert new == []


def test_handoff_expires_when_no_track_appears():
    t = tracker(window_s=15)
    t.request_handoff(4, "Ana", now=100)
    new, expired = t.update(116, [], FRAME)
    assert new == [] and [p.worker_id for p in expired] == [4]


def test_sequential_workers_get_their_own_tracks():
    t = tracker()
    t.request_handoff(4, "Ana", now=100)
    t.update(101, [(1, (50, 400, 150, 700))], FRAME)
    t.request_handoff(5, "Luis", now=120)
    new, _ = t.update(121, [(1, (300, 400, 400, 700)), (2, (50, 400, 150, 700))], FRAME)
    assert new == [(2, 5, "Luis")]
    assert t.worker_for(1) == 4


def test_release_on_exit_ignores_the_track():
    t = tracker()
    t.request_handoff(4, "Ana", now=100)
    t.update(101, [(1, (50, 400, 150, 700))], FRAME)
    t.release_worker(4)
    assert t.worker_for(1) is None and 1 in t.ignored


def test_manual_assignment():
    t = tracker()
    t.assign(33, 8)
    assert t.worker_for(33) == 8
