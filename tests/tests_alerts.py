from backend.alerts import AlertEngine, classify_direction, image_proximity


def obj(label="person", box=(200, 30, 400, 400),
        confidence=0.95):
    return {
        "label": label,
        "confidence": confidence,
        "box": list(box),
    }


def test_direction_regions():
    assert classify_direction([0, 0, 100, 100], 640) == "left"
    assert classify_direction([250, 0, 390, 100], 640) == "ahead"
    assert classify_direction([500, 0, 630, 100], 640) == "right"


def test_near_image_object_generates_alert():
    engine = AlertEngine(cooldown=3)
    result = engine.process(
        [obj("car", (180, 20, 460, 420))], 640, 480
    )
    assert result is not None
    assert result["object"] == "car"
    assert result["proximity_estimate"] == "near"


def test_duplicate_alert_suppressed():
    engine = AlertEngine(cooldown=3)
    detection = obj("person", (200, 30, 400, 400))
    assert engine.process([detection], 640, 480) is not None
    assert engine.process([detection], 640, 480) is None


def test_low_confidence_is_ignored():
    engine = AlertEngine()
    assert engine.process(
        [obj(confidence=0.15)], 640, 480
    ) is None


def test_navigation_context_is_returned():
    engine = AlertEngine(cooldown=0)
    engine.update_navigation({
        "instruction": "Turn left soon",
        "direction": "left",
        "active": True,
    })
    result = engine.process(
        [obj("car", (0, 20, 180, 420))], 640, 480
    )
    assert result["navigation_context"] == "Turn left soon"


def test_proximity_is_heuristic():
    assert image_proximity([100, 10, 300, 400], 640, 480) in {
        "near", "medium", "far"
    }
