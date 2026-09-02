#!/usr/bin/env python3
"""RK3576 <-> cloud relay JSON link test client.

Quick start:
  1. Set CLOUD_SERVER below to the cloud server's public IP.
  2. Run: python3 rk3576_client.py

You may also override the address once:
  python3 rk3576_client.py ws://203.0.113.10:8771
"""

import asyncio
import json
import socket
import sys
import time
from typing import Any, Dict

import websockets


# Replace this once with the public IP or domain of the cloud server.
CLOUD_SERVER = "8.134.118.29"
CLOUD_PORT = 8771
SEND_INTERVAL_SECONDS = 1.0
RECONNECT_DELAY_SECONDS = 2.0


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def default_uri() -> str:
    if CLOUD_SERVER == "YOUR_CLOUD_SERVER_IP":
        raise ValueError(
            "请先修改脚本顶部的 CLOUD_SERVER，或运行："
            "python3 rk3576_client.py ws://云服务器IP:8771"
        )
    return f"ws://{CLOUD_SERVER}:{CLOUD_PORT}"


def make_message(sequence: int) -> Dict[str, Any]:
    """Build a deliberately simple RK3576 -> PC test message."""
    return {
        "source": "rk3576",
        "type": "test_status",
        "seq": sequence,
        "timestamp": now_ms(),
        "data": {
            "hostname": socket.gethostname(),
            "message": "hello from rk3576",
        },
    }


async def sender(websocket: Any) -> None:
    sequence = 1
    while True:
        message = make_message(sequence)
        await websocket.send(json.dumps(message, ensure_ascii=False))
        print(f"[发送] seq={sequence}: {message}", flush=True)
        sequence += 1
        await asyncio.sleep(SEND_INTERVAL_SECONDS)


async def receiver(websocket: Any) -> None:
    async for raw_message in websocket:
        received_at = now_ms()
        try:
            message = json.loads(raw_message)
        except json.JSONDecodeError:
            print(f"[接收] 非法 JSON: {raw_message!r}", flush=True)
            continue

        print(f"[接收] {message}", flush=True)

        # Application-level latency probe. Keep the incoming timestamp intact.
        if message.get("type") == "ping" and "timestamp" in message:
            pong = {
                "source": "rk3576",
                "type": "pong",
                "timestamp": message["timestamp"],
                "received_at": received_at,
            }
            await websocket.send(json.dumps(pong, ensure_ascii=False))
            print(f"[回复] pong: {pong}", flush=True)


async def run(uri: str) -> None:
    while True:
        try:
            print(f"[连接] {uri}", flush=True)
            async with websockets.connect(
                uri,
                ping_interval=20,
                ping_timeout=10,
                max_size=1024 * 1024,
            ) as websocket:
                print("[已连接] 开始双向 JSON 测试", flush=True)
                send_task = asyncio.create_task(sender(websocket))
                receive_task = asyncio.create_task(receiver(websocket))
                done, pending = await asyncio.wait(
                    {send_task, receive_task},
                    return_when=asyncio.FIRST_EXCEPTION,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    task.result()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(
                f"[断开] {type(error).__name__}: {error}; "
                f"{RECONNECT_DELAY_SECONDS:g} 秒后重连",
                flush=True,
            )
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)


def main() -> None:
    try:
        uri = sys.argv[1] if len(sys.argv) > 1 else default_uri()
        if not uri.startswith(("ws://", "wss://")):
            raise ValueError("服务器地址必须以 ws:// 或 wss:// 开头")
        asyncio.run(run(uri))
    except KeyboardInterrupt:
        print("\n[退出] 用户停止程序")
    except ValueError as error:
        print(f"[配置错误] {error}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
