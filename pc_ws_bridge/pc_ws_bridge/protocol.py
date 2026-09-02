"""Pure JSON protocol conversion used by the PC bridge."""

import math
import time
from typing import Any, Dict, Tuple


SOURCE = "pc"
REMOTE_SOURCE = "rk3576"
FRAME_TYPE = "ros_topic"
OUTBOUND_TYPE = "std_msgs/msg/String"
INBOUND_TYPE = "geometry_msgs/msg/Vector3"


class ProtocolError(ValueError):
    """Raised when an incoming JSON value does not match the test protocol."""


def now_ms() -> int:
    """Return the Unix epoch time in whole milliseconds."""
    return time.time_ns() // 1_000_000


def string_frame(
    sequence: int,
    value: str,
    topic: str = "/pc_to_cat",
) -> Dict[str, Any]:
    """Encode a ROS String value as the fixed PC-to-RK3576 frame."""
    return {
        "source": SOURCE,
        "type": FRAME_TYPE,
        "seq": sequence,
        "timestamp": now_ms(),
        "topic": topic,
        "msg_type": OUTBOUND_TYPE,
        "data": {"data": value},
    }


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"data.{field} 必须是数值")
    converted = float(value)
    if not math.isfinite(converted):
        raise ProtocolError(f"data.{field} 必须是有限数值")
    return converted


def parse_vector3_frame(
    frame: Any,
    topic: str = "/cat_to_pc",
) -> Tuple[float, float, float]:
    """Validate an RK3576 frame and return its Vector3 components."""
    if not isinstance(frame, dict):
        raise ProtocolError("JSON 顶层必须是对象")

    expected = {
        "source": REMOTE_SOURCE,
        "type": FRAME_TYPE,
        "topic": topic,
        "msg_type": INBOUND_TYPE,
    }
    for field, expected_value in expected.items():
        if frame.get(field) != expected_value:
            raise ProtocolError(f"字段 {field} 不符合约定")

    for field in ("seq", "timestamp"):
        value = frame.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProtocolError(f"{field} 必须是非负整数")

    data = frame.get("data")
    if not isinstance(data, dict):
        raise ProtocolError("data 必须是对象")

    return tuple(_finite_number(data.get(field), field) for field in ("x", "y", "z"))
