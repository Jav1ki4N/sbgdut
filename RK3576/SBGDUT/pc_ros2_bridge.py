#!/usr/bin/env python3
"""ROS 2 Jazzy PC-side bridge for the phase-two public-network link test.

Local ROS input:
    /pc_to_cat  (std_msgs/msg/String)
Remote ROS output:
    /cat_to_pc  (geometry_msgs/msg/Vector3)
"""

import asyncio
import json
import sys
import time
from typing import Any, Dict

import rclpy
from geometry_msgs.msg import Vector3
from rclpy.node import Node
from std_msgs.msg import String
import websockets


CLOUD_SERVER = "8.134.118.29"
CLOUD_PORT = 8770
RECONNECT_DELAY_SECONDS = 2.0
MAX_MESSAGE_BYTES = 1024 * 1024


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class PcBridge(Node):
    def __init__(self, outgoing: "asyncio.Queue[Dict[str, Any]]") -> None:
        super().__init__("pc_public_ws_bridge")
        self.outgoing = outgoing
        self.sequence = 0
        self.publisher = self.create_publisher(Vector3, "/cat_to_pc", 10)
        self.subscription = self.create_subscription(
            String, "/pc_to_cat", self.on_local_message, 10
        )

    def on_local_message(self, message: String) -> None:
        self.sequence += 1
        frame = {
            "source": "pc",
            "type": "ros_topic",
            "seq": self.sequence,
            "timestamp": now_ms(),
            "topic": "/pc_to_cat",
            "msg_type": "std_msgs/msg/String",
            "data": {"data": message.data},
        }
        if self.outgoing.full():
            self.outgoing.get_nowait()
        self.outgoing.put_nowait(frame)
        self.get_logger().info(f"排队发送 /pc_to_cat seq={self.sequence}")

    def publish_remote(self, frame: Any) -> None:
        if not isinstance(frame, dict):
            raise ValueError("JSON 顶层必须是对象")
        if (
            frame.get("source") != "rk3576"
            or frame.get("type") != "ros_topic"
            or frame.get("topic") != "/cat_to_pc"
            or frame.get("msg_type") != "geometry_msgs/msg/Vector3"
        ):
            raise ValueError("不是允许的 RK3576 Topic 帧")
        data = frame.get("data")
        if not isinstance(data, dict) or not all(
            is_number(data.get(field)) for field in ("x", "y", "z")
        ):
            raise ValueError("Vector3.data 必须包含数值 x、y、z")
        message = Vector3(x=float(data["x"]), y=float(data["y"]), z=float(data["z"]))
        self.publisher.publish(message)
        self.get_logger().info(f"已发布 /cat_to_pc seq={frame.get('seq', '?')}")


async def spin_ros(node: Node) -> None:
    while rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0)
        await asyncio.sleep(0.01)


async def send_frames(websocket: Any, outgoing: "asyncio.Queue[Dict[str, Any]]") -> None:
    while True:
        frame = await outgoing.get()
        await websocket.send(json.dumps(frame, ensure_ascii=False, separators=(",", ":")))


async def receive_frames(websocket: Any, node: PcBridge) -> None:
    async for raw in websocket:
        if isinstance(raw, bytes):
            node.get_logger().warning("忽略二进制消息")
            continue
        try:
            node.publish_remote(json.loads(raw))
        except (json.JSONDecodeError, ValueError) as error:
            node.get_logger().warning(f"忽略无效消息: {error}")


async def connected_session(
    websocket: Any, node: PcBridge, outgoing: "asyncio.Queue[Dict[str, Any]]"
) -> None:
    send_task = asyncio.create_task(send_frames(websocket, outgoing))
    receive_task = asyncio.create_task(receive_frames(websocket, node))
    done, pending = await asyncio.wait(
        {send_task, receive_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        task.result()


async def websocket_loop(
    uri: str, node: PcBridge, outgoing: "asyncio.Queue[Dict[str, Any]]"
) -> None:
    while rclpy.ok():
        try:
            node.get_logger().info(f"连接 {uri}")
            async with websockets.connect(
                uri,
                open_timeout=10,
                ping_interval=20,
                ping_timeout=10,
                max_size=MAX_MESSAGE_BYTES,
            ) as websocket:
                node.get_logger().info("公网中继已连接")
                await connected_session(websocket, node, outgoing)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            node.get_logger().warning(
                f"连接断开: {type(error).__name__}: {error}; "
                f"{RECONNECT_DELAY_SECONDS:g} 秒后重连"
            )
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


async def async_main(uri: str) -> None:
    outgoing: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=1)
    node = PcBridge(outgoing)
    try:
        await asyncio.gather(spin_ros(node), websocket_loop(uri, node, outgoing))
    finally:
        node.destroy_node()


def main() -> None:
    uri = sys.argv[1] if len(sys.argv) > 1 else f"ws://{CLOUD_SERVER}:{CLOUD_PORT}"
    if not uri.startswith(("ws://", "wss://")):
        raise SystemExit("地址必须以 ws:// 或 wss:// 开头")
    rclpy.init()
    try:
        asyncio.run(async_main(uri))
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
