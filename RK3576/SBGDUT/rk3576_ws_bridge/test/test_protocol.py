import pytest

from rk3576_ws_bridge.protocol import (
    ProtocolError,
    parse_string_frame,
    vector3_frame,
)


def valid_string_frame():
    return {
        "source": "pc",
        "type": "ros_topic",
        "seq": 7,
        "timestamp": 123456789,
        "topic": "/pc_to_cat",
        "msg_type": "std_msgs/msg/String",
        "data": {"data": "hello RK3576"},
    }


def test_vector3_frame():
    frame = vector3_frame(3, 1, 2.5, -4)
    assert frame["source"] == "rk3576"
    assert frame["topic"] == "/cat_to_pc"
    assert frame["msg_type"] == "geometry_msgs/msg/Vector3"
    assert frame["data"] == {"x": 1.0, "y": 2.5, "z": -4.0}


def test_parse_string_frame():
    assert parse_string_frame(valid_string_frame()) == "hello RK3576"


@pytest.mark.parametrize("field", ["source", "type", "topic", "msg_type"])
def test_rejects_wrong_identity_fields(field):
    frame = valid_string_frame()
    frame[field] = "wrong"
    with pytest.raises(ProtocolError):
        parse_string_frame(frame)


@pytest.mark.parametrize("field,value", [("seq", True), ("seq", -1), ("timestamp", 1.5)])
def test_rejects_invalid_metadata(field, value):
    frame = valid_string_frame()
    frame[field] = value
    with pytest.raises(ProtocolError):
        parse_string_frame(frame)
