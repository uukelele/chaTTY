import asyncio
import base64, json
import socket, struct
from pathlib import Path
from typing import TypedDict

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import serialization

KEY_DIR = Path('~/.config/chatty').expanduser()
PRIV_KEY = KEY_DIR / 'id_x25519'
PUB_KEY  = KEY_DIR / 'id_x25519.pub'

STUN_SERVERS = [
    ('stun.l.google.com', 19302),
    ('stun1.l.google.com', 19302),
]

class Invite(TypedDict):
    ip: str
    port: str
    pubkey: str

def get_keys() -> tuple[bytes, bytes]:
    KEY_DIR.mkdir(exist_ok=True)

    if not PRIV_KEY.exists():
        priv_key = x25519.X25519PrivateKey.generate()
        priv_bytes = priv_key.private_bytes(
            encoding = serialization.Encoding.Raw,
            format = serialization.PrivateFormat.Raw,
            encryption_algorithm = serialization.NoEncryption(),
        )

        pub_key = priv_key.public_key()
        pub_bytes = pub_key.public_bytes(
            encoding = serialization.Encoding.Raw,
            format = serialization.PublicFormat.Raw,
        )

        PRIV_KEY.write_bytes(priv_bytes)
        PUB_KEY.write_bytes(pub_bytes)

    return PRIV_KEY.read_bytes(), PUB_KEY.read_bytes()

def get_ext_ip(local_port: int = 0) -> tuple[str, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', local_port))
    sock.settimeout(3.0)

    msg = struct.pack("!HHI12s", 0x0001, 0, 0x2112A442, b'\x00'*12)
    for s_host, s_port in STUN_SERVERS:
        try:
            sock.sendto(msg, (s_host, s_port))
            data, _ = sock.recvfrom(2048)
            offset = 20
            while offset < len(data):
                attr_type, attr_length = struct.unpack_from("!HH", data, offset)
                if attr_type == 0x0020:
                    family = data[offset + 5]
                    if family == 0x01:
                        xport = struct.unpack_from("!H", data, offset + 6)[0]
                        port = xport ^ 0x2112
                        xaddr = struct.unpack_from("!I", data, offset + 8)[0]
                        ip = socket.inet_ntoa(struct.pack("!I", xaddr ^ 0x2112A442))
                        return ip, port
                if attr_length == 0:
                    offset += 4
                else:
                    padding = (4 - (attr_length % 4)) % 4
                    offset += 4 + attr_length + padding
        except Exception:
            continue

    return '127.0.0.1', local_port

def gen_invite(ip: str, port: int, pub_bytes: bytes) -> str:
    return base64.urlsafe_b64encode(json.dumps({
        "ip": ip,
        "port": port,
        "pubkey": base64.b64encode(pub_bytes).decode(),
    }).encode()).decode()

def parse_invite(invite: str) -> Invite:
    data = json.loads(base64.urlsafe_b64decode(invite.encode()).decode())
    data['pubkey'] = base64.b64decode(data['pubkey'])
    return data

async def send_msg(writer: asyncio.StreamWriter, data: bytes):
    writer.write(struct.pack('!H', len(data)) + data)
    await writer.drain()

async def recv_msg(reader: asyncio.StreamReader) -> bytes:
    length_bytes = await reader.readexactly(2)
    length = struct.unpack('!H', length_bytes)[0]
    return await reader.readexactly(length)