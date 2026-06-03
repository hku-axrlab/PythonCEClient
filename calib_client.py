"""
calib_client.py  –  WebSocket client for CalibrationEnv (hku-axrlab/CalibrationEnv, refactor branch)

Usage:
    python calib_client.py [--host HOST] [--port PORT] [--rate RATE] [--client-type TYPE]

Defaults:
    host        = localhost
    port        = 4196
    rate        = 1000          (desired incoming data delay in ms)
    client-type = "python"
"""

import asyncio
import json
import argparse
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

import websockets

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("calib_client")


# ---------------------------------------------------------------------------
# Message type constants
# Adjust these strings to match whatever the server actually expects.
# ---------------------------------------------------------------------------
class MsgType:
    CONNECT     = 0  # "clientConnect"
    # Add more types here if needed in future (signal, or authority stuff, maybe?)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass
class Transform:
    """Position + rotation for any tracked entity."""
    pos_x:  float = 0.0
    pos_y:  float = 0.0
    pos_z:  float = 0.0
    rot_x:  float = 0.0
    rot_y:  float = 0.0
    rot_z:  float = 0.0
    rot_w:  float = 1.0


@dataclass
class User:
    """A connected / tracked user (headset, controller, etc.)."""
    id:        str = ""
    home:      str = ""
    name:      str = ""
    boneTransforms: list = field(default_factory=list)
    boneNames: list = field(default_factory=list)
    
    def to_dict(self) -> dict:
        d = asdict(self)
        return d

@dataclass
class CalibObject:
    """A tracked physical or virtual object in the calibration scene (untested)"""
    """A unique object called a 'vRoot' (tag) is expected from every client, if none exists absolute positions are used"""
    """To parse the incoming transforms properly, you will need to make the transforms of objects local to the vRoot sent along (or not sent, in which case absolute is local)"""
    """You can match objects and the correct vRoot via the home GUID"""
    id:         str = ""
    home:       str = ""
    tag:        str = ""
    transform:  Transform = field(default_factory=Transform)
    visible:    bool = True
    active:     bool = True
    data:       dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class WorldModel:
    """Snapshot of the full world state (untested)"""
    users:   list = field(default_factory=list)   # list[User]
    objects: list = field(default_factory=list)   # list[CalibObject]

    def to_dict(self) -> dict:
        return {
            "users":   [u.to_dict() for u in self.users],
            "objects": [o.to_dict() for o in self.objects],
        }


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------
def build_connect_message(client_type: str, send_rate: int) -> dict:
    """
    Initial handshake sent right after the WebSocket connection opens.

    Fields:
        type        – message type identifier expected by the server
        clientType  – a string label for this client ("viewer", "python", …)
        sendRate    – how many world-model updates per second this client wants
    """
    return {
        "msgType":       MsgType.CONNECT,
        "clientType":   client_type,
        "sendRate":     send_rate,
    }

def handle_message(data: dict) -> None:
    """
    Top-level dispatcher.  Extend the if/elif chain for new message types.
    """
    objects = data.get("objects", "")
    users = data.get("users", "")
    
    remoteRoots = {}
    
    # TODO: build vRoot transform dict
    for obj in objects:
        if obj.get("tag") == "vRoot":
            # parse the vRoot transform into a dict
            remoteRoots[obj.get("home")] = obj.get("transform")
            # log.info("transform: %s", remoteRoots[obj.get("home")])
            pass
    
    # parse objects & users however you like
    for obj in objects:
        if obj.get("tag") == "Lamp":
            for var in obj.get("data"):
                if var.get("type") == "colorX":
                    # If you want to get the correct position, calculate it relative to the remoteRoots[obj.get("home")] transform
                    # you'll probably need a math library for this (for the quaternion rotations etc.)
                    # basically: 
                    #   position = ( position - rootPosition ) * rootRotation
                    #   rotation = rotation * rootRotation                    
                    # COLOR INFO:
                    log.info("%s: %s", obj.get("name"), var.get("value"))
                    pass

# ---------------------------------------------------------------------------
# Send helpers  (call these from inside the `run` loop or your own coroutines)
# ---------------------------------------------------------------------------
async def send_json(ws, payload: dict) -> None:
    """Serialise `payload` to JSON and send it over the WebSocket."""
    await ws.send(json.dumps(payload))
    log.debug("Sent: %s", payload.get("msgType", payload))

# ---------------------------------------------------------------------------
# Main client loop
# ---------------------------------------------------------------------------
async def run(host: str, port: int, client_type: str, send_rate: int) -> None:
    uri = f"ws://{host}:{port}"
    log.info("Connecting to %s …", uri)

    async with websockets.connect(uri) as ws:
        log.info("Connected.")

        # 1. Handshake
        await send_json(ws, build_connect_message(client_type, send_rate))
        log.info("Sent clientConnect (type=%s, rate=%d)", client_type, send_rate)

        # 2. Receive loop
        async for raw in ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("Received non-JSON message: %r", raw)
                continue
            handle_message(data)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="CalibrationEnv WebSocket client")
    parser.add_argument("--host",        default="localhost", help="Server hostname or IP")
    parser.add_argument("--port",        default=4196, type=int, help="Server port")
    parser.add_argument("--rate",        default=1000,   type=int, help="Desired incoming update rate (Hz)")
    parser.add_argument("--client-type", default="python",       help="Client type label sent to server")
    
    args = parser.parse_args()

    try:
        asyncio.run(run(args.host, args.port, args.client_type, args.rate))
    except KeyboardInterrupt:
        log.info("Disconnected.")

if __name__ == "__main__":
    main()
