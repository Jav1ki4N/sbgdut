#!/usr/bin/env python3
"""Paired WebSocket JSON relay for PC, viewer, and vehicle-side nodes.

Ports 8770 and 8771 form one bidirectional relay pair. The status node on port
8772 and the viewer on port 8773 form another. Ports 8774 through 8777 accept
independent placeholder connections whose routing is intentionally left for a
later stage.
Run on the cloud server with:

    python relay_server.py

This is a link-test relay. It has no authentication or TLS; restrict all
ports with the cloud security group and Windows Firewall during testing.
"""

import asyncio
from contextlib import AsyncExitStack
import json
import logging
from typing import Any, Dict, Optional

import websockets


HOST = "0.0.0.0"
PC_PORT = 8770
RK3576_PORT = 8771
STATUS_NODE_PORT = 8772
VIEWER_PORT = 8773
RELAY_PORTS = {
    "PC": PC_PORT,
    "RK3576": RK3576_PORT,
    "STATUS_NODE": STATUS_NODE_PORT,
    "VIEWER": VIEWER_PORT,
}
RELAY_TARGETS = {
    "PC": "RK3576",
    "RK3576": "PC",
    "STATUS_NODE": "VIEWER",
    "VIEWER": "STATUS_NODE",
}
PASSIVE_PORTS = {
    "PORT_8774": 8774,
    "PORT_8775": 8775,
    "PORT_8776": 8776,
    "PORT_8777": 8777,
}
MAX_MESSAGE_BYTES = 1024 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gdut-relay")

relay_clients: Dict[str, Any] = {}
passive_clients: Dict[str, Any] = {}
client_lock: Optional[asyncio.Lock] = None


def peer_name(websocket: Any) -> str:
    address = getattr(websocket, "remote_address", None)
    return str(address) if address else "unknown"


async def replace_client(role: str, websocket: Any) -> None:
    """Keep only the newest connection for each role."""
    assert client_lock is not None
    async with client_lock:
        previous = relay_clients.get(role)
        relay_clients[role] = websocket

    if previous is not None and previous is not websocket:
        logger.warning("%s 新连接替换旧连接", role)
        await previous.close(code=4001, reason="replaced by a newer connection")


async def clear_client(role: str, websocket: Any) -> None:
    assert client_lock is not None
    async with client_lock:
        if relay_clients.get(role) is websocket:
            relay_clients.pop(role)


async def current_target(role: str) -> Optional[Any]:
    assert client_lock is not None
    async with client_lock:
        return relay_clients.get(RELAY_TARGETS[role])


async def relay_handler(websocket: Any, role: str) -> None:
    await replace_client(role, websocket)
    logger.info("%s 已连接: %s", role, peer_name(websocket))

    try:
        async for raw_message in websocket:
            if isinstance(raw_message, bytes):
                logger.warning("拒绝来自 %s 的二进制消息 (%d bytes)", role, len(raw_message))
                continue

            try:
                parsed = json.loads(raw_message)
            except json.JSONDecodeError as error:
                logger.warning("拒绝来自 %s 的非法 JSON: %s", role, error)
                continue

            if not isinstance(parsed, (dict, list)):
                logger.warning("拒绝来自 %s 的 JSON 标量", role)
                continue

            target = await current_target(role)
            target_role = RELAY_TARGETS[role]
            if target is None:
                logger.warning("收到 %s 消息，但 %s 尚未连接", role, target_role)
                continue

            try:
                # Forward the original text without changing either side's schema.
                await target.send(raw_message)
                message_type = parsed.get("type", "unknown") if isinstance(parsed, dict) else "array"
                logger.info("%s -> %s | type=%s | bytes=%d", role, target_role, message_type, len(raw_message.encode("utf-8")))
            except websockets.ConnectionClosed:
                logger.warning("%s 消息未转发：对端连接已关闭", role)
    except websockets.ConnectionClosed as event:
        logger.info("%s 连接关闭: code=%s reason=%s", role, event.code, event.reason)
    except Exception:
        logger.exception("处理 %s 连接时发生异常", role)
    finally:
        await clear_client(role, websocket)
        logger.info("%s 已断开: %s", role, peer_name(websocket))


def make_relay_handler(role: str) -> Any:
    """Create a WebSocket handler bound to one side of a relay pair."""

    async def handler(websocket: Any, path: Any = None) -> None:
        del path
        await relay_handler(websocket, role)

    return handler


async def passive_handler(websocket: Any, role: str) -> None:
    """Keep an independent connection open without routing its messages yet."""
    assert client_lock is not None
    async with client_lock:
        previous = passive_clients.get(role)
        passive_clients[role] = websocket

    if previous is not None and previous is not websocket:
        logger.warning("%s 新连接替换旧连接", role)
        await previous.close(code=4001, reason="replaced by a newer connection")

    logger.info("%s 已连接: %s", role, peer_name(websocket))
    try:
        async for raw_message in websocket:
            message_size = (
                len(raw_message)
                if isinstance(raw_message, bytes)
                else len(raw_message.encode("utf-8"))
            )
            logger.info(
                "收到 %s 消息但路由尚未配置 | bytes=%d", role, message_size
            )
    except websockets.ConnectionClosed as event:
        logger.info("%s 连接关闭: code=%s reason=%s", role, event.code, event.reason)
    except Exception:
        logger.exception("处理 %s 连接时发生异常", role)
    finally:
        async with client_lock:
            if passive_clients.get(role) is websocket:
                passive_clients.pop(role)
        logger.info("%s 已断开: %s", role, peer_name(websocket))


def make_passive_handler(role: str) -> Any:
    """Create a WebSocket handler bound to one independent connection role."""

    async def handler(websocket: Any, path: Any = None) -> None:
        del path
        await passive_handler(websocket, role)

    return handler


async def main() -> None:
    global client_lock
    client_lock = asyncio.Lock()

    logger.info("启动双向 JSON 中继")
    for role, port in RELAY_PORTS.items():
        logger.info("%-11s -> ws://<server>:%d", role, port)
    for role, port in PASSIVE_PORTS.items():
        logger.info("%-11s -> ws://<server>:%d (路由未配置)", role, port)

    server_specs = (
        *((make_relay_handler(role), port) for role, port in RELAY_PORTS.items()),
        *((make_passive_handler(role), port) for role, port in PASSIVE_PORTS.items()),
    )

    async with AsyncExitStack() as stack:
        for handler, port in server_specs:
            await stack.enter_async_context(
                websockets.serve(
                    handler,
                    HOST,
                    port,
                    ping_interval=20,
                    ping_timeout=10,
                    max_size=MAX_MESSAGE_BYTES,
                )
            )
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("服务器已停止")
