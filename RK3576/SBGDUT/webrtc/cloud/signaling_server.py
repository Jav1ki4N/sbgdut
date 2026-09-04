#!/usr/bin/env python3
"""One-publisher/one-viewer WebRTC signaling relay.

This service forwards SDP and ICE messages only. WebRTC media travels directly
between peers, or through a separately configured TURN server when required.
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, Optional

import websockets


HOST = os.environ.get("WEBRTC_SIGNAL_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEBRTC_SIGNAL_PORT", "8765"))
MAX_MESSAGE_BYTES = 1024 * 1024
ROLES = ("publisher", "viewer")
PEER_ROLE = {"publisher": "viewer", "viewer": "publisher"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("webrtc-signaling")

clients: Dict[str, Any] = {}
client_lock: Optional[asyncio.Lock] = None


def peer_name(websocket: Any) -> str:
    address = getattr(websocket, "remote_address", None)
    return str(address) if address else "unknown"


def decode_message(raw_message: Any) -> Dict[str, Any]:
    if isinstance(raw_message, bytes):
        raise ValueError("binary messages are not supported")
    try:
        message = json.loads(raw_message)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error}") from error
    if not isinstance(message, dict):
        raise ValueError("message must be a JSON object")
    return message


def validate_signal(message: Dict[str, Any]) -> None:
    message_type = message.get("type")
    if message_type in ("offer", "answer"):
        if not isinstance(message.get("sdp"), str) or not message["sdp"]:
            raise ValueError(f"{message_type}.sdp must be a non-empty string")
        return
    if message_type == "candidate":
        candidate = message.get("candidate")
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be an object")
        if not isinstance(candidate.get("candidate"), str):
            raise ValueError("candidate.candidate must be a string")
        if not isinstance(candidate.get("sdpMLineIndex"), int):
            raise ValueError("candidate.sdpMLineIndex must be an integer")
        return
    raise ValueError("type must be offer, answer, or candidate")


async def register(role: str, websocket: Any) -> None:
    assert client_lock is not None
    async with client_lock:
        previous = clients.get(role)
        clients[role] = websocket

    if previous is not None and previous is not websocket:
        logger.warning("%s new connection replaced the old connection", role)
        await previous.close(code=4001, reason="replaced by a newer connection")


async def unregister(role: str, websocket: Any) -> None:
    assert client_lock is not None
    async with client_lock:
        if clients.get(role) is websocket:
            clients.pop(role)


async def current_client(role: str) -> Optional[Any]:
    assert client_lock is not None
    async with client_lock:
        return clients.get(role)


async def notify_peer_disconnected(role: str) -> None:
    target = await current_client(PEER_ROLE[role])
    if target is None:
        return
    try:
        await target.send(
            json.dumps(
                {"type": "peer-disconnected", "role": role},
                separators=(",", ":"),
            )
        )
    except websockets.ConnectionClosed:
        pass


async def notify_peer_connected(role: str) -> None:
    target = await current_client(PEER_ROLE[role])
    if target is None:
        return
    try:
        await target.send(
            json.dumps(
                {"type": "peer-connected", "role": role},
                separators=(",", ":"),
            )
        )
    except websockets.ConnectionClosed:
        pass


async def handler(websocket: Any, path: Any = None) -> None:
    del path
    role: Optional[str] = None
    address = peer_name(websocket)
    logger.info("connection opened: %s", address)

    try:
        raw_registration = await asyncio.wait_for(websocket.recv(), timeout=10)
        registration = decode_message(raw_registration)
        if registration.get("type") != "register":
            await websocket.close(code=4002, reason="register first")
            return
        role_value = registration.get("role")
        if role_value not in ROLES:
            await websocket.close(code=4003, reason="invalid role")
            return
        role = role_value
        await register(role, websocket)
        await websocket.send(
            json.dumps(
                {"type": "registered", "role": role},
                separators=(",", ":"),
            )
        )
        logger.info("%s registered: %s", role, address)
        await notify_peer_connected(role)

        async for raw_message in websocket:
            try:
                message = decode_message(raw_message)
                validate_signal(message)
            except ValueError as error:
                logger.warning("rejected %s message: %s", role, error)
                continue

            target_role = PEER_ROLE[role]
            target = await current_client(target_role)
            if target is None:
                logger.warning("%s signal dropped: %s is offline", role, target_role)
                continue
            try:
                await target.send(
                    json.dumps(message, ensure_ascii=False, separators=(",", ":"))
                )
                logger.info("%s -> %s | type=%s", role, target_role, message["type"])
            except websockets.ConnectionClosed:
                logger.warning("%s signal dropped: %s disconnected", role, target_role)
    except asyncio.TimeoutError:
        await websocket.close(code=4002, reason="registration timeout")
    except websockets.ConnectionClosed as event:
        logger.info("connection closed: %s code=%s", address, event.code)
    except Exception:
        logger.exception("connection error: %s", address)
    finally:
        if role is not None:
            await unregister(role, websocket)
            await notify_peer_disconnected(role)
            logger.info("%s disconnected: %s", role, address)


async def main() -> None:
    global client_lock
    client_lock = asyncio.Lock()
    logger.info("WebRTC signaling listening on ws://%s:%d", HOST, PORT)
    async with websockets.serve(
        handler,
        HOST,
        PORT,
        ping_interval=20,
        ping_timeout=10,
        max_size=MAX_MESSAGE_BYTES,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("signaling server stopped")
