import math

import pytest

from pc_ws_bridge.protocol import ProtocolError, parse_vector3_frame, string_frame


def valid_vector3_frame():
    return {
        "source": "rk3576",
        "type": "ros_topic",
        "seq": 7,
        "timestamp": 123456789,
        "topic": "/cat_to_pc",
        "msg_type": "geometry_msgs/msg/Vector3",
        "data": {"x": 1, "y": 2.5, "z": -4.0},
    }


def test_string_frame():
    frame = string_frame(3, "hello RK3576")
    assert frame["source"] == "pc"
    assert frame["type"] == "ros_topic"
    assert frame["seq"] == 3
    assert isinstance(frame["timestamp"], int)
    assert frame["topic"] == "/pc_to_cat"
    assert frame["msg_type"] == "std_msgs/msg/String"
    assert frame["data"] == {"data": "hello RK3576"}


def test_parse_vector3_frame():
    assert parse_vector3_frame(valid_vector3_frame()) == (1.0, 2.5, -4.0)


@pytest.mark.parametrize("value", [[], "text", 42, None])
def test_rejects_non_object_root(value):
    with pytest.raises(ProtocolError):
        parse_vector3_frame(value)


@pytest.mark.parametrize("field", ["source", "type", "topic", "msg_type"])
def test_rejects_wrong_identity_fields(field):
    frame = valid_vector3_frame()
    frame[field] = "wrong"
    with pytest.raises(ProtocolError):
        parse_vector3_frame(frame)


@pytest.mark.parametrize(
    "field,value",
    [
        ("seq", True),
        ("seq", -1),
        ("seq", 1.5),
        ("timestamp", False),
        ("timestamp", -1),
        ("timestamp", "123"),
    ],
)
def test_rejects_invalid_metadata(field, value):
    frame = valid_vector3_frame()
    frame[field] = value
    with pytest.raises(ProtocolError):
        parse_vector3_frame(frame)


@pytest.mark.parametrize("value", [None, [], "data"])
def test_rejects_non_object_data(value):
    frame = valid_vector3_frame()
    frame["data"] = value
    with pytest.raises(ProtocolError):
        parse_vector3_frame(frame)


@pytest.mark.parametrize("field", ["x", "y", "z"])
@pytest.mark.parametrize("value", [None, "1.0", True])
def test_rejects_missing_or_non_numeric_components(field, value):
    frame = valid_vector3_frame()
    frame["data"][field] = value
    with pytest.raises(ProtocolError):
        parse_vector3_frame(frame)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_rejects_non_finite_components(value):
    frame = valid_vector3_frame()
    frame["data"]["x"] = value
    with pytest.raises(ProtocolError):
        parse_vector3_frame(frame)


def test_custom_topics_are_honored():
    outgoing = string_frame(1, "test", "/custom_out")
    incoming = valid_vector3_frame()
    incoming["topic"] = "/custom_in"
    assert outgoing["topic"] == "/custom_out"
    assert parse_vector3_frame(incoming, "/custom_in") == (1.0, 2.5, -4.0)
