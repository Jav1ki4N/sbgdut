#!/usr/bin/env python3
"""Publish the RK3576 USB camera to the GDUT WebRTC viewer."""

import asyncio
import json
import logging
import os
import signal
from typing import Any, Optional

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstSdp", "1.0")
gi.require_version("GstWebRTC", "1.0")
from gi.repository import GLib, Gst, GstSdp, GstWebRTC  # noqa: E402

import websockets


SIGNAL_URL = os.environ.get("WEBRTC_SIGNAL_URL", "ws://203.195.243.106:8765")
CAMERA = os.environ.get("WEBRTC_CAMERA", "/dev/video0")
STUN_URL = os.environ.get(
    "WEBRTC_STUN_URL", "stun://stun.miwifi.com:3478"
)
TURN_URL = os.environ.get(
    "WEBRTC_TURN_URL",
    "turn://gdut:a731f8fb76bb516e021623e71255bfd6@203.195.243.106:3478",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("rk-webrtc-publisher")


class Publisher:
    def __init__(self) -> None:
        Gst.init(None)
        self.loop = asyncio.get_running_loop()
        self.outgoing: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.websocket: Optional[Any] = None
        self.pipeline: Optional[Gst.Pipeline] = None
        self.webrtc: Optional[Gst.Element] = None
        self.offer_in_progress = False

    def build_pipeline(self) -> None:
        description = f"""
            webrtcbin name=webrtc bundle-policy=max-bundle
                stun-server={STUN_URL}
                turn-server={TURN_URL}
            v4l2src device={CAMERA} !
                image/jpeg,width=640,height=360,framerate=30/1 !
                jpegparse ! jpegdec ! videoconvert ! videorate !
                video/x-raw,format=NV12,framerate=15/1 !
                mpph264enc rc-mode=cbr bps=600000 bps-min=300000
                    bps-max=800000 gop=15 !
                h264parse config-interval=-1 !
                video/x-h264,stream-format=byte-stream,alignment=au !
                rtph264pay config-interval=-1 pt=96 !
                application/x-rtp,media=video,encoding-name=H264,
                    clock-rate=90000,payload=96 ! webrtc.
        """
        pipeline = Gst.parse_launch(description)
        webrtc = pipeline.get_by_name("webrtc")
        if webrtc is None:
            raise RuntimeError("failed to create webrtcbin")
        self.pipeline = pipeline
        self.webrtc = webrtc
        webrtc.connect("on-ice-candidate", self.on_ice_candidate)

        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_bus_message)

        result = pipeline.set_state(Gst.State.PLAYING)
        if result == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("failed to start GStreamer pipeline")
        logger.info("camera pipeline started: %s (640x360@15, 600 kbps)", CAMERA)

    def stop_pipeline(self) -> None:
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None
        self.webrtc = None
        self.offer_in_progress = False

    def on_bus_message(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            logger.error("GStreamer error: %s; %s", error, debug or "no details")
            self.loop.call_soon_threadsafe(self.outgoing.put_nowait, {"type": "fatal"})
        elif message.type == Gst.MessageType.WARNING:
            warning, debug = message.parse_warning()
            logger.warning("GStreamer warning: %s; %s", warning, debug or "no details")

    def on_ice_candidate(
        self, _webrtc: Gst.Element, mline_index: int, candidate: str
    ) -> None:
        message = {
            "type": "candidate",
            "candidate": {
                "candidate": candidate,
                "sdpMLineIndex": int(mline_index),
                "sdpMid": "video0",
            },
        }
        self.loop.call_soon_threadsafe(self.outgoing.put_nowait, message)

    def create_offer(self) -> None:
        if self.webrtc is None or self.offer_in_progress:
            return
        self.offer_in_progress = True
        promise = Gst.Promise.new_with_change_func(self.on_offer_created, None, None)
        self.webrtc.emit("create-offer", None, promise)

    def on_offer_created(
        self, promise: Gst.Promise, _user_data: Any, _unused: Any
    ) -> None:
        try:
            reply = promise.get_reply()
            offer = reply.get_value("offer")
            if offer is None:
                raise RuntimeError("webrtcbin returned no offer")
            assert self.webrtc is not None
            self.webrtc.emit("set-local-description", offer, Gst.Promise.new())
            message = {"type": "offer", "sdp": offer.sdp.as_text()}
            self.loop.call_soon_threadsafe(self.outgoing.put_nowait, message)
            logger.info("SDP offer created")
        except Exception:
            logger.exception("failed to create SDP offer")
        finally:
            self.offer_in_progress = False

    def set_answer(self, sdp_text: str) -> None:
        result, sdp = GstSdp.SDPMessage.new_from_text(sdp_text)
        if result != GstSdp.SDPResult.OK:
            raise RuntimeError(f"invalid answer SDP: {result}")
        answer = GstWebRTC.WebRTCSessionDescription.new(
            GstWebRTC.WebRTCSDPType.ANSWER, sdp
        )
        assert self.webrtc is not None
        self.webrtc.emit("set-remote-description", answer, Gst.Promise.new())
        logger.info("browser SDP answer applied")

    async def send_messages(self) -> None:
        while True:
            message = await self.outgoing.get()
            if message.get("type") == "fatal":
                raise RuntimeError("GStreamer pipeline failed")
            if self.websocket is not None:
                await self.websocket.send(json.dumps(message, separators=(",", ":")))

    async def receive_messages(self) -> None:
        assert self.websocket is not None
        async for raw in self.websocket:
            message = json.loads(raw)
            message_type = message.get("type")
            if message_type == "registered":
                logger.info("signaling registered; creating offer")
                self.create_offer()
            elif message_type == "peer-connected" and message.get("role") == "viewer":
                logger.info("viewer connected; creating offer")
                self.create_offer()
            elif message_type == "answer":
                self.set_answer(message["sdp"])
            elif message_type == "candidate":
                candidate = message["candidate"]
                assert self.webrtc is not None
                self.webrtc.emit(
                    "add-ice-candidate",
                    int(candidate["sdpMLineIndex"]),
                    candidate["candidate"],
                )
            elif message_type == "peer-disconnected":
                logger.info("viewer disconnected; waiting for reconnection")

    async def run_connection(self) -> None:
        logger.info("connecting signaling: %s", SIGNAL_URL)
        async with websockets.connect(
            SIGNAL_URL, open_timeout=10, ping_interval=20, ping_timeout=10
        ) as websocket:
            self.websocket = websocket
            await websocket.send('{"type":"register","role":"publisher"}')
            sender = asyncio.create_task(self.send_messages())
            receiver = asyncio.create_task(self.receive_messages())
            done, pending = await asyncio.wait(
                (sender, receiver), return_when=asyncio.FIRST_EXCEPTION
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()

    async def run(self) -> None:
        self.build_pipeline()
        try:
            while True:
                try:
                    await self.run_connection()
                except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed) as error:
                    logger.warning("signaling disconnected: %s; retrying in 2s", error)
                finally:
                    self.websocket = None
                await asyncio.sleep(2)
        finally:
            self.stop_pipeline()


async def pump_glib() -> None:
    context = GLib.MainContext.default()
    while True:
        while context.pending():
            context.iteration(False)
        await asyncio.sleep(0.01)


async def main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        loop.add_signal_handler(getattr(signal, name), stop_event.set)

    publisher = Publisher()
    publisher_task = asyncio.create_task(publisher.run())
    glib_task = asyncio.create_task(pump_glib())
    stop_task = asyncio.create_task(stop_event.wait())
    done, _pending = await asyncio.wait(
        (publisher_task, stop_task), return_when=asyncio.FIRST_COMPLETED
    )
    if publisher_task in done:
        publisher_task.result()
    publisher_task.cancel()
    glib_task.cancel()
    stop_task.cancel()
    await asyncio.gather(publisher_task, glib_task, stop_task, return_exceptions=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
