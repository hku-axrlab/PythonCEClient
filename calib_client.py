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

import numpy as np
from scipy.spatial.transform import Rotation as R

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

remoteRoots = {}

# This gets called when a mesage was parsed
# Use this to check the worldModel and find objects / users etc.
def onMessageParsed() -> None:
    # Example of how to go through the objects
    for id in worldModel.objects:
        obj = worldModel.objects[id]
        
        if obj.tag == "Femto":
            # log.info('%s, %s, %s', obj.transform.pos_x, obj.transform.pos_y, obj.transform.pos_z)
            pass
            
    # Example of how to go through the users        
    for id in worldModel.users:
        usr = worldModel.users[id]
        
        for tN in range(0,len(usr.boneNames)):
            # log.info('%s: %s, %s, %s', usr.boneNames[tN], usr.boneTransforms[tN].pos_x, usr.boneTransforms[tN].pos_y, usr.boneTransforms[tN].pos_z)
            pass

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
class Transform:
    """Position + rotation for any tracked entity."""
    pos_x:      float = 0.0
    pos_y:      float = 0.0
    pos_z:      float = 0.0
    rot_x:      float = 0.0
    rot_y:      float = 0.0
    rot_z:      float = 0.0
    rot_w:      float = 1.0
    sc_x:       float = 1.0
    sc_y:       float = 1.0
    sc_z:       float = 1.0
    
    def makeRelative(self, transform : 'Transform') -> 'Transform':
        myPos = np.array([self.pos_x, self.pos_y, self.pos_z])
        myRot = R.from_quat([self.rot_x, self.rot_y, self.rot_z, self.rot_w])
        
        otherPos = np.array([transform.pos_x, transform.pos_y, transform.pos_z])
        otherRot = R.from_quat([transform.rot_x, transform.rot_y, transform.rot_z, transform.rot_w])
        
        otherPos = myRot.apply(otherPos - myPos )
        otherRot = myRot.__mul__(otherRot).as_quat()
        
        transform.pos_x = otherPos[0]
        transform.pos_y = otherPos[1]
        transform.pos_z = otherPos[2]
        
        transform.rot_x = otherRot[0]
        transform.rot_y = otherRot[1]
        transform.rot_z = otherRot[2]
        transform.rot_w = otherRot[3]
        
        return transform
    
@dataclass
class ObjectVariable:
    type:       str = ""
    name:       str = ""
    value = ""
    
    def to_dict(self) -> dict:
        d = asdict(self)
        return d

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
    name:       str = ""
    home:       str = ""
    tag:        str = ""
    transform:  Transform = field(default_factory=Transform)
    visible:    bool = True
    active:     bool = True
    data:       list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class WorldModel:
    """Snapshot of the full world state (untested)"""
    users:   dict = field(default_factory=dict)   # dict{id, User}
    objects: dict = field(default_factory=dict)   # dict{id, CalibObject}

    def to_dict(self) -> dict:
        return {
            "users":   [u.to_dict() for u in self.users],
            "objects": [o.to_dict() for o in self.objects],
        }

worldModel : WorldModel = WorldModel()


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
    
def parseTransform(transform: dict) -> Transform:
    t : Transform = Transform()
    t.pos_x = transform.get("position").get("X")
    t.pos_y = transform.get("position").get("Y")
    t.pos_z = transform.get("position").get("Z")
    
    t.rot_x = transform.get("rotation").get("X")
    t.rot_y = transform.get("rotation").get("Y")
    t.rot_z = transform.get("rotation").get("Z")
    t.rot_w = transform.get("rotation").get("W")
    
    t.sc_x = transform.get("scale").get("X")
    t.sc_y = transform.get("scale").get("Y")
    t.sc_z = transform.get("scale").get("Z")
    return t
    
def parseData(d: dict) -> ObjectVariable:
    var : ObjectVariable = ObjectVariable()    
    var.type = d.get("type")
    var.name = d.get("name")
    var.value = d.get("value")    
    return var

def handle_message(data: dict) -> None:
    """
    Top-level dispatcher.  Extend the if/elif chain for new message types.
    """
    objects = data.get("objects", "")
    users = data.get("users", "")
    
    # TODO: build vRoot transform dict
    for obj in objects:
        if obj.get("tag") == "vRoot":
            # parse the vRoot transform into a dict
            remoteRoots[obj.get("home")] = parseTransform(obj.get("transform"))
            # log.info("transform: %s", remoteRoots[obj.get("home")])
            pass
    
    # parse objects & users however you like
    for obj in objects:
        # Get or create the instance to create/update
        calibObject : CalibObject = CalibObject() # field(default_factory=CalibObject)
        
        if obj.get("id") in worldModel.objects:
            calibObject = worldModel.objects[obj.get("id")]
        
        # parse the object
        calibObject.id = obj.get("id")
        calibObject.name = obj.get("name")
        calibObject.home = obj.get("home")
        calibObject.tag = obj.get("tag")
        calibObject.transform = parseTransform(obj.get("transform"))
        
        if calibObject.home in remoteRoots:
            remoteRoot = remoteRoots[calibObject.home]
            calibObject.transform = remoteRoot.makeRelative(calibObject.transform)
        
        calibObject.data = []
        for i in obj.get("data"):
            calibObject.data.append(parseData(i))
    
        for var in obj.get("data"):
            if var.get("type") == "live":
                calibObject.live = var.get("value")
            if var.get("type") == "visible":
                calibObject.active = var.get("value")
        
        worldModel.objects[obj.get("id")] = calibObject
        
    for usr in users:
        calibUser : User =  User()
        
        if usr.get("id") in worldModel.users:
            calibUser = worldModel.users[usr.get("id")]
        
        # parse the object
        calibUser.id = usr.get("id")
        calibUser.name = usr.get("name")
        calibUser.home = usr.get("home")
        calibUser.tag = usr.get("tag")
        
        
        calibUser.boneNames = []
        calibUser.boneTransforms = []
        for tIn in usr.get("boneTransforms"):
            tOut : Transform = parseTransform(tIn)
            if calibUser.home in remoteRoots:
                tOut = remoteRoots[calibUser.home].makeRelative(tOut)
            calibUser.boneTransforms.append(tOut)
        
        for tN in usr.get("boneNames"):
            calibUser.boneNames.append(tN)
            
        worldModel.users[usr.get("id")] = calibUser
    
    # TODO: Parse Users
    #    if obj.get("tag") == "Lamp":
    #        for var in obj.get("data"):
    #            if var.get("type") == "colorX":
    #                # If you want to get the correct position, calculate it relative to the remoteRoots[obj.get("home")] transform
    #                # you'll probably need a math library for this (for the quaternion rotations etc.)
    #                # basically: 
    #                #   position = ( position - rootPosition ) * rootRotation
    #                #   rotation = rotation * rootRotation                    
    #                # COLOR INFO:
    #                log.info("%s: %s", obj.get("name"), var.get("value"))
    #                pass
    
    onMessageParsed()

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
