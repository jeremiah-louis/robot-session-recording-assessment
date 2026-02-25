"""Simulated robot that streams telemetry over WebSocket."""

import argparse
import asyncio
import base64
import io
import json
import math
import random
import time
import uuid

import websockets
from PIL import Image

# Helpers to simulate realtime robot
def generate_joint_states(t: float) -> dict:
    """6-DOF joint positions + velocities with sinusoidal motion."""
    positions = [math.sin(t * (0.5 + i * 0.3)) * (1.0 + i * 0.2) for i in range(6)]
    velocities = [math.cos(t * (0.5 + i * 0.3)) * (0.5 + i * 0.3) for i in range(6)]
    return {
        "type": "message",
        "topic": "/joint_states",
        "timestamp": t,
        "data_type": "float32[]",
        "data": positions + velocities,
    }


def generate_gripper_state(t: float) -> dict:
    """Gripper with simulated pick-and-place cycle."""
    cycle = (t % 10) / 10  # 10-second cycle
    position = 0.8 if cycle < 0.5 else 0.2  # open/close
    force = random.uniform(0.1, 2.0) if position < 0.5 else 0.0
    contact = position < 0.5 and force > 1.0
    return {
        "type": "message",
        "topic": "/gripper_state",
        "timestamp": t,
        "data_type": "float32[]",
        "data": [position, force, float(contact)],
    }


def generate_camera_frame(t: float) -> dict:
    """Small colored image that changes over time."""
    r = int(127 + 127 * math.sin(t * 0.5))
    g = int(127 + 127 * math.sin(t * 0.3 + 2))
    b = int(127 + 127 * math.sin(t * 0.7 + 4))
    img = Image.new("RGB", (96, 96), (r, g, b))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=50)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    return {
        "type": "message",
        "topic": "/camera/front",
        "timestamp": t,
        "data_type": "image_ref",
        "image_base64": b64,
    }


async def run(server_url: str, duration: float, session_id: str):
    async with websockets.connect(server_url) as ws:
        # Start session
        await ws.send(json.dumps({
            "type": "session_start",
            "session_id": session_id,
            "robot_type": "mock_6dof",
            "fps": 10.0,
            "topics": {
                "/joint_states": {"data_type": "float32[]", "shape": [12]},
                "/gripper_state": {"data_type": "float32[]", "shape": [3]},
                "/camera/front": {"data_type": "image_ref", "shape": [96, 96, 3]},
            },
        }))
        print(f"Session started: {session_id}")

        start = time.monotonic()
        frame = 0
        while (elapsed := time.monotonic() - start) < duration:
            t = elapsed

            # Joint states + gripper at ~10Hz
            for msg in [generate_joint_states(t), generate_gripper_state(t)]:
                msg["frame_index"] = frame
                await ws.send(json.dumps(msg))

            # Camera at ~5Hz (every other frame)
            if frame % 2 == 0:
                cam_msg = generate_camera_frame(t)
                cam_msg["frame_index"] = frame
                await ws.send(json.dumps(cam_msg))

            frame += 1
            await asyncio.sleep(0.1)  # 10Hz

        # End session
        await ws.send(json.dumps({"type": "session_end"}))
        print(f"Session ended: {session_id} ({frame} frames, {elapsed:.1f}s)")


def main():
    parser = argparse.ArgumentParser(description="Mock robot telemetry client")
    parser.add_argument("--server-url", default="ws://localhost:8000/ws/ingest")
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--session-id", default=None)
    args = parser.parse_args()

    session_id = args.session_id or f"live-{uuid.uuid4().hex[:8]}"
    asyncio.run(run(args.server_url, args.duration, session_id))


if __name__ == "__main__":
    main()
