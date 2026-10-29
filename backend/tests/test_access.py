from app.access.controller import State


def event_types(db):
    return [e["type"] for e in db.query("SELECT type FROM events ORDER BY id")]


def attempts(db):
    return [a["result"] for a in db.query("SELECT result FROM access_attempts ORDER BY id")]


def do_entry(controller, clock, worker):
    controller.handle_event({"evt": "presence", "sensor": 1})
    controller.handle_event({"evt": "finger", "result": "match", "slot": worker["fingerprint_slot"]})


def test_entry_happy_path(controller, device, db, clock, worker, callbacks):
    controller.handle_event({"evt": "presence", "sensor": 1})
    assert controller.state == State.ENTRY_AUTH
    assert device.sent("auth_start")
    assert device.last_lcd() == ("Ponga su huella", "Intento 1/3")

    controller.handle_event({"evt": "finger", "result": "match", "slot": 1})
    assert controller.state == State.ENTRY_WAIT_CROSS
    assert device.sent("door")[-1]["open"] is True
    assert device.last_lcd() == ("Bienvenido", "Ana Perez")   # sin tildes para el LCD

    clock.advance(2)
    controller.handle_event({"evt": "presence", "sensor": 2})
    assert controller.state == State.CLOSING
    assert db.inside_worker_ids() == {worker["id"]}
    assert callbacks["entered"] == [worker["id"]]

    clock.advance(1.5)
    controller.tick()
    assert controller.state == State.IDLE
    assert device.sent("door")[-1]["open"] is False
    assert attempts(db) == ["granted"]


def test_next_worker_blocked_until_process_completes(controller, device, clock, worker):
    do_entry(controller, clock, worker)
    assert controller.state == State.ENTRY_WAIT_CROSS
    before = len(device.sent("auth_start"))
    controller.handle_event({"evt": "presence", "sensor": 1})   # la fila sigue en el sensor 1
    assert controller.state == State.ENTRY_WAIT_CROSS
    assert len(device.sent("auth_start")) == before


def test_three_failures_raise_intruder_alert(controller, device, db, clock):
    controller.handle_event({"evt": "presence", "sensor": 1})
    for expected in ("Intento 2/3", "Intento 3/3"):
        controller.handle_event({"evt": "finger", "result": "nomatch"})
        assert device.last_lcd()[1] == expected
    controller.handle_event({"evt": "finger", "result": "nomatch"})
    assert controller.state == State.DENIED
    assert device.last_lcd() == ("VETE!!", "Acceso denegado")
    assert "intruder_alert" in event_types(db)
    assert attempts(db).count("no_match") == 3 and "intruder" in attempts(db)
    assert db.query("SELECT * FROM attendance") == []

    clock.advance(6)
    controller.tick()
    assert controller.state == State.IDLE


def test_unknown_slot_counts_as_failed_attempt(controller, db):
    controller.handle_event({"evt": "presence", "sensor": 1})
    controller.handle_event({"evt": "finger", "result": "match", "slot": 77})
    assert controller.state == State.ENTRY_AUTH
    assert attempts(db) == ["no_match"]


def test_no_crossing_discards_the_registration(controller, device, db, clock, worker, callbacks):
    do_entry(controller, clock, worker)
    clock.advance(10.5)
    controller.tick()
    assert controller.state == State.IDLE
    assert db.query("SELECT * FROM attendance") == []
    assert callbacks["entered"] == []
    assert device.sent("door")[-1]["open"] is False
    assert attempts(db) == ["granted", "no_crossing"]
    assert "crossing_timeout" in event_types(db)


def test_exit_flow_uses_sensors_in_reverse(controller, device, db, clock, worker, callbacks):
    db.record_attendance(worker["id"], "IN")
    controller.handle_event({"evt": "presence", "sensor": 2})
    assert controller.state == State.EXIT_AUTH
    controller.handle_event({"evt": "finger", "result": "match", "slot": 1})
    assert controller.state == State.EXIT_WAIT_CROSS
    controller.handle_event({"evt": "presence", "sensor": 1})
    assert controller.state == State.CLOSING
    assert db.inside_worker_ids() == set()
    assert callbacks["exited"] == [worker["id"]]


def test_sensor2_without_finger_times_out_and_is_ignored(controller, device, db, clock):
    controller.handle_event({"evt": "presence", "sensor": 2})
    assert controller.state == State.EXIT_AUTH
    controller.handle_event({"evt": "finger", "result": "timeout"})
    assert controller.state == State.IDLE
    assert db.query("SELECT * FROM attendance") == []
    # durante el enfriamiento no se vuelve a disparar
    controller.handle_event({"evt": "presence", "sensor": 2})
    assert controller.state == State.IDLE
    clock.advance(6)
    controller.handle_event({"evt": "presence", "sensor": 2})
    assert controller.state == State.EXIT_AUTH


def test_entry_rejected_if_already_inside(controller, device, db, clock, worker):
    db.record_attendance(worker["id"], "IN")
    do_entry(controller, clock, worker)
    assert controller.state == State.DENIED
    assert attempts(db) == ["already_inside"]
    assert not device.sent("door")


def test_exit_rejected_if_not_inside(controller, db, worker):
    controller.handle_event({"evt": "presence", "sensor": 2})
    controller.handle_event({"evt": "finger", "result": "match", "slot": 1})
    assert attempts(db) == ["not_inside"]


def test_auth_deadline_backup_if_device_goes_silent(controller, device, db, clock):
    controller.handle_event({"evt": "presence", "sensor": 1})
    clock.advance(19)
    controller.tick()
    assert controller.state == State.IDLE
    assert device.sent("auth_cancel")


def test_enrollment_success_stores_slot(controller, device, db):
    w = db.create_worker("Luis")
    ok, _ = controller.start_enroll(w["id"])
    assert ok and controller.state == State.ENROLLING
    assert device.sent("enroll")[-1] == {"cmd": "enroll", "slot": 1}
    for step in ("place1", "remove", "place2"):
        controller.handle_event({"evt": "enroll", "step": step, "slot": 1})
    controller.handle_event({"evt": "enroll", "step": "ok", "slot": 1})
    assert controller.state == State.IDLE
    assert db.get_worker(w["id"])["fingerprint_slot"] == 1


def test_enrollment_failure_keeps_worker_without_slot(controller, db):
    w = db.create_worker("Luis")
    controller.start_enroll(w["id"])
    controller.handle_event({"evt": "enroll", "step": "fail", "msg": "Las huellas no coinciden"})
    assert controller.state == State.IDLE
    assert db.get_worker(w["id"])["fingerprint_slot"] is None
    assert "enroll_failed" in event_types(db)


def test_enroll_refused_when_busy_or_offline(controller, db, clock):
    w = db.create_worker("Luis")
    controller.handle_event({"evt": "presence", "sensor": 1})
    assert controller.start_enroll(w["id"])[0] is False


def test_delete_fingerprint_frees_slot_and_commands_device(controller, device, db, worker):
    ok, _ = controller.delete_fingerprint(worker["id"])
    assert ok
    assert device.sent("delete")[-1] == {"cmd": "delete", "slot": 1}
    assert db.get_worker(worker["id"])["fingerprint_slot"] is None


def test_assistance_button_creates_request(controller, db):
    controller.handle_event({"evt": "assist", "where": "work_area"})
    rows = db.query("SELECT * FROM assistance_requests")
    assert len(rows) == 1 and rows[0]["source"] == "work_area" and rows[0]["status"] == "open"
    assert "assistance_request" in event_types(db)


def test_device_offline_and_back_online(controller, db, clock):
    clock.advance(7)
    controller.tick()
    assert controller.device_online is False
    controller.handle_event({"evt": "hb"})
    assert controller.device_online is True
    types = event_types(db)
    assert "device_offline" in types and types.count("device_online") == 2


def test_manual_door_override_closes_itself(controller, device, clock):
    controller.set_door(True)
    assert device.sent("door")[-1]["open"] is True
    clock.advance(9)
    controller.tick()
    assert device.sent("door")[-1]["open"] is False
