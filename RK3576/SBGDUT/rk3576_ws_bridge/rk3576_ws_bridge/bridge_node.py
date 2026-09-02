"""RK3576 ROS 2 Humble WebSocket bridge node."""

import asyncio
import json
from typing import Any, Dict

import rclpy
from geometry_msgs.msg import Vector3
from rclpy.node import Node
from std_msgs.msg import String
import websockets

from .protocol import ProtocolError, parse_string_frame, vector3_frame


class BridgeNode(Node):
    def __init__(self, outgoing: "asyncio.Queue[Dict[str, Any]]") -> None:
        super().__init__("rk3576_ws_bridge")
        self.declare_parameter("server_uri", "ws://8.134.118.29:8771")
        self.declare_parameter("outbound_topic", "/cat_to_pc")
        self.declare_parameter("inbound_topic", "/pc_to_cat")
        self.declare_parameter("reconnect_delay", 2.0)
        self.server_uri = str(self.get_parameter("server_uri").value)
        self.outbound_topic = str(self.get_parameter("outbound_topic").value)
        self.inbound_topic = str(self.get_parameter("inbound_topic").value)
        self.reconnect_delay = float(self.get_parameter("reconnect_delay").value)
        if not self.server_uri.startswith(("ws://", "wss://")):
            raise ValueError("server_uri 必须以 ws:// 或 wss:// 开头")
        if self.reconnect_delay <= 0:
            raise ValueError("reconnect_delay 必须大于 0")

        self.outgoing = outgoing
        self.sequence = 0
        self.publisher = self.create_publisher(String, self.inbound_topic, 10)
        self.subscription = self.create_subscription(
            Vector3, self.outbound_topic, self.on_local_message, 10
        )

    def on_local_message(self, message: Vector3) -> None:
        self.sequence += 1
        frame = vector3_frame(
            self.sequence,
            message.x,
            message.y,
            message.z,
            self.outbound_topic,
        )
        if self.outgoing.full():
            self.outgoing.get_nowait()
        self.outgoing.put_nowait(frame)
        self.get_logger().info(
            f"Topic -> JSON: {self.outbound_topic}, seq={self.sequence}"
        )

    def publish_remote(self, frame: Any) -> None:
        value = parse_string_frame(frame, self.inbound_topic)
        self.publisher.publish(String(data=value))
        self.get_logger().info(
            f"JSON -> Topic: {self.inbound_topic}, seq={frame['seq']}"
        )


async def spin_ros(node: Node) -> None:
    while rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0)
        await asyncio.sleep(0.01)


async def send_frames(websocket: Any, queue: "asyncio.Queue[Dict[str, Any]]") -> None:
    while True:
        frame = await queue.get()
        await websocket.send(json.dumps(frame, ensure_ascii=False, separators=(",", ":")))


async def receive_frames(websocket: Any, node: BridgeNode) -> None:
    async for raw in websocket:
        if isinstance(raw, bytes):
            node.get_logger().warning("忽略二进制消息")
            continue
        try:
            node.publish_remote(json.loads(raw))
        except (json.JSONDecodeError, ProtocolError) as error:
            node.get_logger().warning(f"忽略无效消息: {error}")


async def connected_session(
    websocket: Any,
    node: BridgeNode,
    queue: "asyncio.Queue[Dict[str, Any]]",
) -> None:
    tasks = {
        asyncio.create_task(send_frames(websocket, queue)),
        asyncio.create_task(receive_frames(websocket, node)),
    }
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        task.result()


async def websocket_loop(
    node: BridgeNode, queue: "asyncio.Queue[Dict[str, Any]]"
) -> None:
    while rclpy.ok():
        try:
            node.get_logger().info(f"正在连接 {node.server_uri}")
            async with websockets.connect(
                node.server_uri,
                open_timeout=10,
                ping_interval=20,
                ping_timeout=10,
                max_size=1024 * 1024,
            ) as websocket:
                node.get_logger().info("公网中继已连接")
                await connected_session(websocket, node, queue)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            node.get_logger().warning(
                f"连接断开: {type(error).__name__}: {error}; "
                f"{node.reconnect_delay:g} 秒后重连"
            )
            await asyncio.sleep(node.reconnect_delay)


async def run() -> None:
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=1)
    node = BridgeNode(queue)
    try:
        await asyncio.gather(spin_ros(node), websocket_loop(node, queue))
    finally:
        node.destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()
