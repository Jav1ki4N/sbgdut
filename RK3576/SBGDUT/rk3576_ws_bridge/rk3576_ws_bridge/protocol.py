"""Pure JSON protocol conversion used by the RK3576 bridge."""

import time
from typing import Any, Dict


SOURCE = "rk3576"
REMOTE_SOURCE = "pc"
FRAME_TYPE = "ros_topic"
OUTBOUND_TYPE = "geometry_msgs/msg/Vector3"
INBOUND_TYPE = "std_msgs/msg/String"


class ProtocolError(ValueError):
    """Raised when an incoming JSON value does not match the test protocol."""


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def vector3_frame(
    sequence: int,
    x: float,
    y: float,
    z: float,
    topic: str = "/cat_to_pc",
) -> Dict[str, Any]:
    return {
        "source": SOURCE,
        "type": FRAME_TYPE,
        "seq": sequence,
        "timestamp": now_ms(),
        "topic": topic,
        "msg_type": OUTBOUND_TYPE,
        "data": {"x": float(x), "y": float(y), "z": float(z)},
    }


def parse_string_frame(frame: Any, topic: str = "/pc_to_cat") -> str:
    if not isinstance(frame, dict):
        raise ProtocolError("JSON 顶层必须是对象")
    expected = {
        "source": REMOTE_SOURCE,
        "type": FRAME_TYPE,
        "topic": topic,
        "msg_type": INBOUND_TYPE,
    }
    for field, value in expected.items():
        if frame.get(field) != value:
            raise ProtocolError(f"字段 {field} 不符合约定")
    data = frame.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("data"), str):
        raise ProtocolError("String.data 必须是字符串")
    sequence = frame.get("seq")
    timestamp = frame.get("timestamp")
    if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
        raise ProtocolError("seq 必须是非负整数")
    if not isinstance(timestamp, int) or isinstance(timestamp, bool) or timestamp < 0:
        raise ProtocolError("timestamp 必须是非负整数")
    return data["data"]
