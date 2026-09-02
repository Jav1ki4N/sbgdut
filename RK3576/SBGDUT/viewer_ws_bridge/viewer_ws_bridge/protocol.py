"""Validation and normalization for the Qt viewer JSON protocol."""

import json
import math
import time
from typing import Any, Dict


class ProtocolError(ValueError):
    """Raised when a JSON value does not follow the viewer protocol."""


def now_ms() -> int:
    """Return Unix epoch time in milliseconds."""
    return time.time_ns() // 1_000_000


def decode_json(raw: str) -> Dict[str, Any]:
    """Decode one strict JSON object, rejecting NaN and Infinity."""
    try:
        value = json.loads(
            raw,
            parse_constant=lambda constant: (_ for _ in ()).throw(
                ProtocolError(f"不允许非有限数值 {constant}")
            ),
        )
    except json.JSONDecodeError as error:
        raise ProtocolError(f"JSON 语法错误: {error.msg}") from error
    if not isinstance(value, dict):
        raise ProtocolError("JSON 顶层必须是对象")
    return value


def encode_json(frame: Dict[str, Any]) -> str:
    """Encode a compact standards-compliant JSON object."""
    return json.dumps(
        frame,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProtocolError(f"{field} 必须是数值")
    converted = float(value)
    if not math.isfinite(converted):
        raise ProtocolError(f"{field} 必须是有限数值")
    if not minimum <= converted <= maximum:
        raise ProtocolError(f"{field} 超出范围 [{minimum:g}, {maximum:g}]")
    return converted


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProtocolError(f"{field} 必须是大于等于 {minimum} 的整数")
    return value


def parse_ping(frame: Any) -> Dict[str, Any]:
    """Validate a ping and construct its pong response."""
    if not isinstance(frame, dict) or frame.get("type") != "ping":
        raise ProtocolError("不是 ping 消息")
    timestamp = _integer(frame.get("timestamp"), "timestamp")
    return {"type": "pong", "timestamp": timestamp}


def parse_control(
    frame: Any,
    current_time_ms: int | None = None,
    max_age_ms: int = 2000,
) -> Dict[str, Any]:
    """Validate and normalize a viewer control message."""
    if not isinstance(frame, dict) or frame.get("type") != "control":
        raise ProtocolError("不是 control 消息")

    mode = frame.get("mode")
    if mode not in ("manual", "replay"):
        raise ProtocolError("mode 必须是 manual 或 replay")
    enable = frame.get("enable")
    if not isinstance(enable, bool):
        raise ProtocolError("enable 必须是布尔值")

    sequence = _integer(frame.get("seq"), "seq", 1)
    timestamp = _integer(frame.get("timestamp"), "timestamp")
    current = now_ms() if current_time_ms is None else current_time_ms
    if timestamp < current - max_age_ms:
        raise ProtocolError("控制消息已过期")
    if timestamp > current + max_age_ms:
        raise ProtocolError("控制消息时间戳超前")

    normalized = {
        "type": "control",
        "steer": _number(frame.get("steer"), "steer", -1.0, 1.0),
        "throttle": _number(frame.get("throttle"), "throttle", 0.0, 1.0),
        "brake": _number(frame.get("brake"), "brake", 0.0, 1.0),
        "gear": _integer(frame.get("gear"), "gear", -1),
        "mode": mode,
        "enable": enable,
        "timestamp": timestamp,
        "seq": sequence,
    }
    if normalized["gear"] not in (-1, 0, 1):
        raise ProtocolError("gear 必须是 -1、0 或 1")
    if not enable:
        normalized.update(steer=0.0, throttle=0.0, brake=1.0, gear=0)
    return normalized


def safe_control(reason: str = "safety_stop") -> Dict[str, Any]:
    """Construct a non-driving control record for the dummy ROS topic."""
    return {
        "type": "control",
        "steer": 0.0,
        "throttle": 0.0,
        "brake": 1.0,
        "gear": 0,
        "mode": "manual",
        "enable": False,
        "timestamp": now_ms(),
        "seq": 0,
        "reason": reason,
    }


def parse_status(frame: Any) -> Dict[str, Any]:
    """Validate and normalize a complete local status message."""
    if not isinstance(frame, dict) or frame.get("type") != "status":
        raise ProtocolError("状态消息 type 必须是 status")
    traffic = frame.get("traffic")
    if not isinstance(traffic, str) or traffic.lower() not in (
        "green",
        "red",
        "stop",
    ):
        raise ProtocolError("traffic 必须是 green、red 或 stop")
    return {
        "type": "status",
        "x": _number(frame.get("x"), "x", -1.0e9, 1.0e9),
        "y": _number(frame.get("y"), "y", -1.0e9, 1.0e9),
        "yaw": _number(frame.get("yaw"), "yaw", -1.0e9, 1.0e9),
        "speed": _number(frame.get("speed"), "speed", -1.0e6, 1.0e6),
        "battery": _number(frame.get("battery"), "battery", 0.0, 1.0e6),
        "traffic": traffic.lower(),
    }
