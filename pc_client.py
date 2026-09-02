#!/usr/bin/env python3
"""PC <-> cloud relay <-> RK3576 JSON link test client.

Run with:
    python3 pc_client.py
"""

import asyncio
import json
import socket
import sys
import time
from typing import Any, Dict

import websockets


CLOUD_SERVER = "8.134.118.29"
CLOUD_PORT = 8770
SEND_INTERVAL_SECONDS = 1.0
RECONNECT_DELAY_SECONDS = 2.0


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def make_command(sequence: int) -> Dict[str, Any]:
    """Build a PC -> RK3576 message with a different payload schema."""
    return {
        "source": "pc",
        "type": "test_command",
        "seq": sequence,
        "timestamp": now_ms(),
        "command": {
            "name": "link_test",
            "value": sequence,
            "message": "hello from pc",
        },
    }


async def sender(websocket: Any) -> None:
    sequence = 1
    while True:
        command = make_command(sequence)
        await websocket.send(json.dumps(command, ensure_ascii=False))
        print(f"[发送指令] seq={sequence}: {command}", flush=True)

        ping = {
            "source": "pc",
            "type": "ping",
            "seq": sequence,
            "timestamp": now_ms(),
        }
        await websocket.send(json.dumps(ping, ensure_ascii=False))
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

        if isinstance(message, dict) and message.get("type") == "pong":
            timestamp = message.get("timestamp")
            if isinstance(timestamp, (int, float)):
                rtt_ms = max(0, received_at - int(timestamp))
                print(f"[延迟] RTT={rtt_ms} ms，估算单向约 {rtt_ms / 2:.1f} ms", flush=True)
                continue

        print(f"[接收数据] {message}", flush=True)


async def run(uri: str) -> None:
    while True:
        try:
            print(f"[连接] {uri}", flush=True)
            async with websockets.connect(
                uri,
                open_timeout=10,
                ping_interval=20,
                ping_timeout=10,
                max_size=1024 * 1024,
            ) as websocket:
                print("[已连接] 开始 PC <-> RK3576 双向测试", flush=True)
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
    uri = sys.argv[1] if len(sys.argv) > 1 else f"ws://{CLOUD_SERVER}:{CLOUD_PORT}"
    if not uri.startswith(("ws://", "wss://")):
        print("[配置错误] 地址必须以 ws:// 或 wss:// 开头", file=sys.stderr)
        raise SystemExit(2)

    try:
        asyncio.run(run(uri))
    except KeyboardInterrupt:
        print("\n[退出] 用户停止程序")


if __name__ == "__main__":
    main()
