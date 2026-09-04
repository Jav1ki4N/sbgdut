#!/usr/bin/env python3
"""PC <-> cloud <-> RK3576 WebSocket JSON relay.

The PC connects to port 8770 and the RK3576 connects to port 8771.
An additional, independent viewer connection can use port 8772. Navigation
routing and message semantics for that connection are intentionally left for a
later stage.
Run on the cloud server with:

    python relay_server.py

This is a link-test relay. It has no authentication or TLS; restrict all
ports with the cloud security group and Windows Firewall during testing.
"""

import asyncio
import json
import logging
from typing import Any, Optional

import websockets


HOST = "0.0.0.0"
PC_PORT = 8770
RK3576_PORT = 8771
NAVIGATION_PORT = 8772
MAX_MESSAGE_BYTES = 1024 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gdut-relay")

pc_client: Optional[Any] = None
rk3576_client: Optional[Any] = None
navigation_client: Optional[Any] = None
client_lock: Optional[asyncio.Lock] = None


def peer_name(websocket: Any) -> str:
    address = getattr(websocket, "remote_address", None)
    return str(address) if address else "unknown"


async def replace_client(role: str, websocket: Any) -> None:
    """Keep only the newest connection for each role."""
    global pc_client, rk3576_client

    assert client_lock is not None
    async with client_lock:
        previous = pc_client if role == "PC" else rk3576_client
        if role == "PC":
            pc_client = websocket
        else:
            rk3576_client = websocket

    if previous is not None and previous is not websocket:
        logger.warning("%s 新连接替换旧连接", role)
        await previous.close(code=4001, reason="replaced by a newer connection")


async def clear_client(role: str, websocket: Any) -> None:
    global pc_client, rk3576_client

    assert client_lock is not None
    async with client_lock:
        if role == "PC" and pc_client is websocket:
            pc_client = None
        elif role == "RK3576" and rk3576_client is websocket:
            rk3576_client = None


async def current_target(role: str) -> Optional[Any]:
    assert client_lock is not None
    async with client_lock:
        return rk3576_client if role == "PC" else pc_client


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
            if target is None:
                logger.warning("收到 %s 消息，但对端尚未连接", role)
                continue

            try:
                # Forward the original text without changing either side's schema.
                await target.send(raw_message)
                message_type = parsed.get("type", "unknown") if isinstance(parsed, dict) else "array"
                logger.info("%s -> %s | type=%s | bytes=%d", role, "RK3576" if role == "PC" else "PC", message_type, len(raw_message.encode("utf-8")))
            except websockets.ConnectionClosed:
                logger.warning("%s 消息未转发：对端连接已关闭", role)
    except websockets.ConnectionClosed as event:
        logger.info("%s 连接关闭: code=%s reason=%s", role, event.code, event.reason)
    except Exception:
        logger.exception("处理 %s 连接时发生异常", role)
    finally:
        await clear_client(role, websocket)
        logger.info("%s 已断开: %s", role, peer_name(websocket))


async def pc_handler(websocket: Any, path: Any = None) -> None:
    del path
    await relay_handler(websocket, "PC")


async def rk3576_handler(websocket: Any, path: Any = None) -> None:
    del path
    await relay_handler(websocket, "RK3576")


async def navigation_handler(websocket: Any, path: Any = None) -> None:
    """Keep an independent viewer connection open on the navigation port."""
    global navigation_client

    del path
    assert client_lock is not None
    async with client_lock:
        previous = navigation_client
        navigation_client = websocket

    if previous is not None and previous is not websocket:
        logger.warning("NAVIGATION 新连接替换旧连接")
        await previous.close(code=4001, reason="replaced by a newer connection")

    logger.info("NAVIGATION 已连接: %s", peer_name(websocket))
    try:
        async for raw_message in websocket:
            message_size = (
                len(raw_message)
                if isinstance(raw_message, bytes)
                else len(raw_message.encode("utf-8"))
            )
            logger.info(
                "收到 NAVIGATION 消息但路由尚未配置 | bytes=%d", message_size
            )
    except websockets.ConnectionClosed as event:
        logger.info(
            "NAVIGATION 连接关闭: code=%s reason=%s", event.code, event.reason
        )
    except Exception:
        logger.exception("处理 NAVIGATION 连接时发生异常")
    finally:
        async with client_lock:
            if navigation_client is websocket:
                navigation_client = None
        logger.info("NAVIGATION 已断开: %s", peer_name(websocket))


async def main() -> None:
    global client_lock
    client_lock = asyncio.Lock()

    logger.info("启动双向 JSON 中继")
    logger.info("PC     -> ws://<server>:%d", PC_PORT)
    logger.info("RK3576 -> ws://<server>:%d", RK3576_PORT)
    logger.info("NAV    -> ws://<server>:%d", NAVIGATION_PORT)

    async with websockets.serve(
        pc_handler,
        HOST,
        PC_PORT,
        ping_interval=20,
        ping_timeout=10,
        max_size=MAX_MESSAGE_BYTES,
    ), websockets.serve(
        rk3576_handler,
        HOST,
        RK3576_PORT,
        ping_interval=20,
        ping_timeout=10,
        max_size=MAX_MESSAGE_BYTES,
    ), websockets.serve(
        navigation_handler,
        HOST,
        NAVIGATION_PORT,
        ping_interval=20,
        ping_timeout=10,
        max_size=MAX_MESSAGE_BYTES,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("服务器已停止")
