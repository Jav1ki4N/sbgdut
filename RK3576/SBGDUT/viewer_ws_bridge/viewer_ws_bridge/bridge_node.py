"""ROS 2 Humble bridge for safe Qt viewer integration testing."""

import asyncio
import time
from typing import Any, Dict, Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import websockets

from .protocol import (
    ProtocolError,
    decode_json,
    encode_json,
    parse_control,
    parse_ping,
    parse_status,
    safe_control,
)


class ViewerBridgeNode(Node):
    """Expose validated viewer frames on dummy String topics."""

    def __init__(self, outgoing: "asyncio.Queue[Dict[str, Any]]") -> None:
        super().__init__("viewer_ws_bridge")
        self.declare_parameter("server_uri", "ws://8.134.118.29:8771")
        self.declare_parameter("control_topic", "/viewer/control_test")
        self.declare_parameter("status_topic", "/viewer/status_test")
        self.declare_parameter("reconnect_delay", 2.0)
        self.declare_parameter("control_timeout", 0.5)
        self.declare_parameter("max_message_age", 2.0)

        self.server_uri = str(self.get_parameter("server_uri").value)
        self.control_topic = str(self.get_parameter("control_topic").value)
        self.status_topic = str(self.get_parameter("status_topic").value)
        self.reconnect_delay = float(self.get_parameter("reconnect_delay").value)
        self.control_timeout = float(self.get_parameter("control_timeout").value)
        self.max_message_age_ms = int(
            float(self.get_parameter("max_message_age").value) * 1000
        )
        if not self.server_uri.startswith(("ws://", "wss://")):
            raise ValueError("server_uri 必须以 ws:// 或 wss:// 开头")
        if min(self.reconnect_delay, self.control_timeout) <= 0:
            raise ValueError("重连和控制超时参数必须大于 0")
        if self.max_message_age_ms <= 0:
            raise ValueError("max_message_age 必须大于 0")

        self.outgoing = outgoing
        self.last_sequence = -1
        self.last_control_time: Optional[float] = None
        self.stop_latched = True
        self.control_publisher = self.create_publisher(String, self.control_topic, 10)
        self.status_subscription = self.create_subscription(
            String, self.status_topic, self.on_local_status, 10
        )
        self.timeout_timer = self.create_timer(0.1, self.check_control_timeout)

    def begin_session(self) -> None:
        """Allow sequence numbering to restart after a new viewer connection."""
        self.last_sequence = -1

    def _publish_control(self, frame: Dict[str, Any]) -> None:
        self.control_publisher.publish(String(data=encode_json(frame)))

    def publish_safe_stop(self, reason: str) -> None:
        """Publish one latched safety record to the dummy control topic."""
        if self.stop_latched:
            return
        self._publish_control(safe_control(reason))
        self.stop_latched = True
        self.get_logger().warning(f"发布测试安全停止: {reason}")

    def handle_control(self, frame: Any) -> None:
        """Validate sequence and publish one normalized dummy control record."""
        control = parse_control(frame, max_age_ms=self.max_message_age_ms)
        if control["seq"] <= self.last_sequence:
            raise ProtocolError("seq 重复或倒退")
        self.last_sequence = control["seq"]
        self.last_control_time = time.monotonic()
        self.stop_latched = not control["enable"]
        self._publish_control(control)
        self.get_logger().info(f"viewer control -> {self.control_topic}, seq={control['seq']}")

    def check_control_timeout(self) -> None:
        """Stop the dummy stream once when viewer control becomes stale."""
        if self.last_control_time is None or self.stop_latched:
            return
        if time.monotonic() - self.last_control_time > self.control_timeout:
            self.publish_safe_stop("control_timeout")

    def on_local_status(self, message: String) -> None:
        """Validate a local status JSON string and queue its newest value."""
        try:
            status = parse_status(decode_json(message.data))
        except ProtocolError as error:
            self.get_logger().warning(f"忽略无效本地状态: {error}")
            return
        if self.outgoing.full():
            self.outgoing.get_nowait()
        self.outgoing.put_nowait(status)


async def spin_ros(node: ViewerBridgeNode) -> None:
    """Service ROS callbacks in the asyncio thread."""
    while rclpy.ok():
        rclpy.spin_once(node, timeout_sec=0)
        await asyncio.sleep(0.01)


async def send_frames(websocket: Any, queue: "asyncio.Queue[Dict[str, Any]]") -> None:
    """Send validated local status frames to the viewer."""
    while True:
        await websocket.send(encode_json(await queue.get()))


async def receive_frames(websocket: Any, node: ViewerBridgeNode) -> None:
    """Handle viewer ping and control frames."""
    async for raw in websocket:
        if isinstance(raw, bytes):
            node.get_logger().warning("忽略二进制消息")
            continue
        try:
            frame = decode_json(raw)
            frame_type = frame.get("type")
            if frame_type == "ping":
                await websocket.send(encode_json(parse_ping(frame)))
            elif frame_type == "control":
                node.handle_control(frame)
            else:
                raise ProtocolError("只接受 ping 或 control 消息")
        except ProtocolError as error:
            node.get_logger().warning(f"忽略无效 viewer 消息: {error}")


async def connected_session(
    websocket: Any,
    node: ViewerBridgeNode,
    queue: "asyncio.Queue[Dict[str, Any]]",
) -> None:
    """Run both directions of one relay connection."""
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
    node: ViewerBridgeNode,
    queue: "asyncio.Queue[Dict[str, Any]]",
) -> None:
    """Maintain the RK3576 relay connection."""
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
                node.begin_session()
                node.get_logger().info("viewer 公网中继已连接")
                await connected_session(websocket, node, queue)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            node.publish_safe_stop("websocket_disconnected")
            node.get_logger().warning(
                f"连接断开: {type(error).__name__}: {error}; "
                f"{node.reconnect_delay:g} 秒后重连"
            )
            await asyncio.sleep(node.reconnect_delay)


async def run() -> None:
    """Run ROS and WebSocket processing together."""
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=1)
    node = ViewerBridgeNode(queue)
    try:
        await asyncio.gather(spin_ros(node), websocket_loop(node, queue))
    finally:
        node.publish_safe_stop("bridge_shutdown")
        node.destroy_node()


def main(args=None) -> None:
    """Run the bridge until interrupted."""
    rclpy.init(args=args)
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()
