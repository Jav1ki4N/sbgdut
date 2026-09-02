import math

import pytest

from viewer_ws_bridge.protocol import (
    ProtocolError,
    decode_json,
    encode_json,
    parse_control,
    parse_ping,
    parse_status,
    safe_control,
)


NOW = 1_788_364_800_000


def valid_control():
    return {
        "type": "control",
        "steer": 0.12,
        "throttle": 0.35,
        "brake": 0.0,
        "gear": 1,
        "mode": "manual",
        "enable": True,
        "timestamp": NOW,
        "seq": 42,
    }


def valid_status():
    return {
        "type": "status",
        "x": 1.234,
        "y": 2.345,
        "yaw": 0.785,
        "speed": 0.8,
        "battery": 24.6,
        "traffic": "green",
    }


def test_json_round_trip():
    frame = {"type": "status", "text": "中文"}
    assert decode_json(encode_json(frame)) == frame


@pytest.mark.parametrize("raw", ["[]", "42", '"text"', "null"])
def test_decode_rejects_non_object(raw):
    with pytest.raises(ProtocolError):
        decode_json(raw)


@pytest.mark.parametrize("raw", ["{", '{"x":NaN}', '{"x":Infinity}'])
def test_decode_rejects_invalid_json(raw):
    with pytest.raises(ProtocolError):
        decode_json(raw)


def test_ping_returns_same_timestamp():
    assert parse_ping({"type": "ping", "timestamp": 123}) == {
        "type": "pong",
        "timestamp": 123,
    }


@pytest.mark.parametrize("timestamp", [True, -1, 1.2, "123", None])
def test_ping_rejects_invalid_timestamp(timestamp):
    with pytest.raises(ProtocolError):
        parse_ping({"type": "ping", "timestamp": timestamp})


def test_control_is_normalized():
    parsed = parse_control(valid_control(), current_time_ms=NOW)
    assert parsed["steer"] == 0.12
    assert parsed["throttle"] == 0.35
    assert parsed["enable"] is True
    assert parsed["seq"] == 42


def test_disabled_control_is_forced_safe():
    frame = valid_control()
    frame.update(enable=False, steer=0.8, throttle=1.0, brake=0.0, gear=1)
    parsed = parse_control(frame, current_time_ms=NOW)
    assert parsed["steer"] == 0.0
    assert parsed["throttle"] == 0.0
    assert parsed["brake"] == 1.0
    assert parsed["gear"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("steer", -1.01),
        ("steer", 1.01),
        ("throttle", -0.01),
        ("throttle", 1.01),
        ("brake", -0.01),
        ("brake", 1.01),
        ("steer", True),
        ("throttle", "0.5"),
        ("brake", math.nan),
    ],
)
def test_control_rejects_invalid_numeric_fields(field, value):
    frame = valid_control()
    frame[field] = value
    with pytest.raises(ProtocolError):
        parse_control(frame, current_time_ms=NOW)


@pytest.mark.parametrize("gear", [-2, 2, True, 1.0, "1"])
def test_control_rejects_invalid_gear(gear):
    frame = valid_control()
    frame["gear"] = gear
    with pytest.raises(ProtocolError):
        parse_control(frame, current_time_ms=NOW)


@pytest.mark.parametrize("mode", ["auto", "", 1, None])
def test_control_rejects_invalid_mode(mode):
    frame = valid_control()
    frame["mode"] = mode
    with pytest.raises(ProtocolError):
        parse_control(frame, current_time_ms=NOW)


@pytest.mark.parametrize("enable", [0, 1, "true", None])
def test_control_rejects_non_boolean_enable(enable):
    frame = valid_control()
    frame["enable"] = enable
    with pytest.raises(ProtocolError):
        parse_control(frame, current_time_ms=NOW)


@pytest.mark.parametrize("seq", [0, -1, True, 1.5, "1"])
def test_control_rejects_invalid_sequence(seq):
    frame = valid_control()
    frame["seq"] = seq
    with pytest.raises(ProtocolError):
        parse_control(frame, current_time_ms=NOW)


@pytest.mark.parametrize("offset", [-2001, 2001])
def test_control_rejects_stale_or_future_timestamp(offset):
    frame = valid_control()
    frame["timestamp"] = NOW + offset
    with pytest.raises(ProtocolError):
        parse_control(frame, current_time_ms=NOW, max_age_ms=2000)


def test_safe_control_cannot_drive():
    frame = safe_control("test")
    assert frame["enable"] is False
    assert frame["throttle"] == 0.0
    assert frame["brake"] == 1.0
    assert frame["gear"] == 0
    assert frame["reason"] == "test"


def test_status_is_normalized():
    frame = valid_status()
    frame["traffic"] = "GREEN"
    parsed = parse_status(frame)
    assert parsed["traffic"] == "green"
    assert parsed["battery"] == 24.6


@pytest.mark.parametrize("field", ["x", "y", "yaw", "speed", "battery"])
@pytest.mark.parametrize("value", [None, True, "1", math.inf])
def test_status_rejects_invalid_numbers(field, value):
    frame = valid_status()
    frame[field] = value
    with pytest.raises(ProtocolError):
        parse_status(frame)


@pytest.mark.parametrize("traffic", ["yellow", "", 1, None])
def test_status_rejects_invalid_traffic(traffic):
    frame = valid_status()
    frame["traffic"] = traffic
    with pytest.raises(ProtocolError):
        parse_status(frame)
