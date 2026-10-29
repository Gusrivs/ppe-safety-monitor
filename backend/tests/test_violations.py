from app.vision.violations import COMPLIANT, NOT_DETECTED, Observation, ViolationMonitor


def bad(track=1, worker=None, missing=("helmet",)):
    return Observation(track, NOT_DETECTED, missing, worker)


def good(track=1, worker=None):
    return Observation(track, COMPLIANT, (), worker)


def run(monitor, start, end, make, step=1.0):
    events, t = [], start
    while t <= end:
        events += monitor.update(t, [make()])
        t += step
    return events


def test_no_warning_before_30_seconds():
    m = ViolationMonitor()
    assert run(m, 0, 29, bad) == []


def test_warns_at_30_seconds_once_per_cooldown():
    m = ViolationMonitor()
    events = run(m, 0, 59, bad)
    assert [e.kind for e in events] == ["violation"]
    assert events[0].missing == ("helmet",)
    assert events[0].duration_s >= 30
    # a los 90 s (30 s + 60 s de enfriamiento) vuelve a advertir
    events = run(m, 60, 95, bad)
    assert len([e for e in events if e.kind == "violation"]) == 1


def test_single_good_frame_does_not_reset_the_counter():
    m = ViolationMonitor()
    run(m, 0, 20, bad)
    m.update(21, [good()])              # un fotograma bueno suelto
    events = run(m, 22, 35, bad)
    assert any(e.kind == "violation" for e in events)


def test_three_seconds_of_compliance_resets_and_resolves():
    m = ViolationMonitor()
    run(m, 0, 35, bad)
    events = run(m, 36, 40, good)
    assert [e.kind for e in events] == ["resolved"]
    # tras resolver, hay que acumular otros 30 s para volver a advertir
    assert run(m, 41, 60, bad) == []


def test_indeterminate_frames_neither_count_nor_reset():
    m = ViolationMonitor()
    run(m, 0, 20, bad)
    for t in range(21, 30):
        m.update(t, [Observation(1, "indeterminate")])
    events = run(m, 30, 31, bad)
    assert any(e.kind == "violation" for e in events)


def test_cooldown_is_per_worker_even_if_track_id_changes():
    m = ViolationMonitor()
    run(m, 0, 40, lambda: bad(track=1, worker=5))
    # el tracker pierde el id 1 y la misma persona reaparece como track 2 (mismo worker)
    events = run(m, 41, 100, lambda: bad(track=2, worker=5))
    violations = [e for e in events if e.kind == "violation"]
    assert all(e.worker_id == 5 for e in violations)
    assert len(violations) <= 1       # el enfriamiento de 60 s se respeta por trabajador


def test_untracked_worker_uses_track_key():
    m = ViolationMonitor()
    events = run(m, 0, 31, lambda: bad(track=9, worker=None))
    assert events[0].key == "track:9" and events[0].worker_id is None


def test_lost_track_is_closed():
    m = ViolationMonitor()
    run(m, 0, 35, bad)
    events = m.update(50, [])           # no se ve al track durante >10 s
    assert [e.kind for e in events] == ["resolved"]
