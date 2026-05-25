import json, zlib, base64

from aiortc import RTCSessionDescription

def encode_sdp(sdp: RTCSessionDescription) -> str:
    return base64.urlsafe_b64encode(zlib.compress(json.dumps({
        'sdp': sdp.sdp,
        'type': sdp.type,
    }).encode())).decode()

def decode_sdp(encoded: str) -> RTCSessionDescription:
    data = json.loads(zlib.decompress(base64.urlsafe_b64decode(encoded.encode())).decode())
    return RTCSessionDescription(**data)