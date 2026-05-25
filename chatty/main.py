from asyncer import asyncify

import os, random, base64, asyncio

from noise.connection import NoiseConnection, Keypair

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Label, Input, Button, RichLog
from textual.reactive import reactive

from .network import get_keys, get_ext_ip, gen_invite, parse_invite, send_msg, recv_msg

class ChaTTY(App):
    CSS = """
    Screen {
        background: $boost;
    }

    #left-panel {
        width: 35%;
        border-right: tall $primary;
        padding: 1;
        background: $surface;
    }

    #right-panel {
        width: 65%;
        padding: 1;
    }

    .panel-title {
        text-align: center;
        background: $accent;
        color: $text;
        text-style: bold;
        padding: 1;
    }

    .field-label {
        color: $text-muted;
        margin-top: 1;
        text-style: bold;
    }

    #chat-box {
        height: 80%;
        border: round $primary;
        background: $surface;
    }

    #chat-input-container {
        height: 20%;
        margin-top: 1;
    }

    Button {
        margin-top: 1;
        width: 100%;
    }

    Input {
        margin-bottom: 1;
    }

    #invite-container {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
    }

    #invite-input {
        width: 70%;
    }

    #copy-btn {
        width: 30%;
        margin: 0;
    }
    """

    local_ip = reactive("Loading...")
    local_port = reactive(19747)
    invite_string = reactive("")
    is_listening = reactive(False)
    is_connected = reactive(False)
    peer_name = reactive("")

    theme = "catppuccin-frappe"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.writer = None
        self.reader = None

        self.noise = None
        self.server = None



    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(
                Label("Profile", classes="panel-title"),

                Label("Nickname:", classes="field-label"),
                Input(value=os.getenv("USER", f"User_{random.randint(1000, 9999)}"), id="nick-input"),

                Label("Public Key Hash", classes="field-label"),
                Label(id="pubkey-label"),

                Label("IP Address", classes="field-label"),
                Label(id="ip-label"),

                Label("Listening on port:", classes="field-label"),
                Input(value="19747", id="port-input", type="integer"),

                Button("Start Listening", variant="success", id="listen-btn"),

                Label("Invite Code:", classes="field-label"),
                Horizontal(
                    Input("Generating...", id="invite-input", disabled=True),
                    Button("Copy", variant="primary", id="copy-btn"),
                    id="invite-container",
                ),

                id="left-panel",
            ),

            Vertical(
                Label("Messages", classes="panel-title"),

                Vertical(
                    Label("Enter Invite Code", classes="field-label"),
                    Input(id="peer-invite-input"),
                    Button("Connect", variant="primary", id="connect-btn"),
                    id="connect-area",
                ),

                Vertical(
                    RichLog(id="chat-box", wrap=True),

                    Horizontal(
                        Input(placeholder="Start typing...", id="msg-input"),
                        Button("Send", variant="success", id="send-btn"),
                        Button("Disconnect", variant="error", id="disconnect-btn"),

                        id="chat-input-container",
                    ),

                    id="chat-area",
                ),

                id="right-panel"
            )
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.priv_bytes, self.pub_bytes = get_keys()

        pub_b64 = base64.b64encode(self.pub_bytes).decode()
        short_pub = pub_b64[:12] + '...' + pub_b64[-4:]
        self.query_one('#pubkey-label').update(short_pub)

        self.query_one('#chat-area').display = False

        asyncio.create_task(self.update_stun_info(19747))

    def watch_is_connected(self, is_connected: bool) -> None:
        try:
            self.query_one('#connect-area').display = not is_connected
            self.query_one('#chat-area').display = is_connected
        except: pass

    def watch_is_listening(self, is_listening: bool) -> None:
        try:
            self.query_one('#port-input').disabled = is_listening
            self.query_one('#listen-btn').disabled = is_listening
        except: pass

    async def update_stun_info(self, local_port: int):
        self.query_one("#ip-label").update('Resolving...')
        ip, port = await asyncify(get_ext_ip)(local_port)

        self.local_ip = ip
        self.local_port = port

        self.query_one('#ip-label').update(f'{ip}:{port}')

        self.invite_string = gen_invite(ip, port, self.pub_bytes)
        self.query_one('#invite-input').value = self.invite_string

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if  event.button.id == 'listen-btn':
            port = int(self.query_one('#port-input').value)
            await self.start_listening_server(port)
        elif event.button.id == 'connect-btn':
            invite_string = self.query_one('#peer-invite-input').value
            if invite_string: await self.initiate_connection(invite_string)
        elif event.button.id == 'send-btn':
            await self.send_chat_message()
        elif event.button.id == 'disconnect-btn':
            await self.disconnect()
        elif event.button.id == 'copy-btn':
            if self.invite_string:
                self.copy_to_clipboard(self.invite_string)
                self.notify("Invite Code Copied!", severity="information")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "msg-input":
            await self.send_chat_message()

    async def start_listening_server(self, port: int):
        try:
            self.server = await asyncio.start_server(
                self.handle_incoming, '0.0.0.0', port
            )
            self.is_listening = True
            self.notify(f"Listening on port {port}", severity="information")
        except Exception as e:
            self.notify(f"Server Error: {e}", severity="error")

    async def handle_incoming(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        if self.is_connected:
            writer.close()
            await writer.wait_closed()
            return
        
        chat_box = self.query_one('#chat-box', RichLog)
        chat_box.clear()
        self.is_connected = True
        chat_box.write("[yellow]System: Peer connecting... Starting handshake.[/yellow]")

        nick = self.query_one('#nick-input').value.strip() or "User"

        try:
            proto = NoiseConnection.from_name(b'Noise_XK_25519_ChaChaPoly_SHA256')
            proto.set_as_responder()
            proto.set_keypair_from_private_bytes(Keypair.STATIC, self.priv_bytes)
            proto.start_handshake()

            ciphertext1 = await recv_msg(reader)
            _ = proto.read_message(ciphertext1)

            ciphertext2 = proto.write_message(payload=nick.encode())
            await send_msg(writer, ciphertext2)

            ciphertext3 = await recv_msg(reader)
            payload = proto.read_message(ciphertext3)

            assert proto.handshake_finished

            self.noise = proto
            self.reader = reader
            self.writer = writer
            self.peer_name = payload.decode(errors='ignore') or 'Anonymous'

            chat_box.write("[green]System: Secure Tunnel Established.[/green]")

            asyncio.create_task(self.read_loop())

        except Exception as e:
            chat_box.write(f"[red]Handshake Failed: {e}[/red]")
            self.is_connected = False
            writer.close()
            try: await writer.wait_closed()
            except: pass

    async def initiate_connection(self, invite_str: str):
        chat_box = self.query_one("#chat-box", RichLog)
        chat_box.clear()

        try:
            invite = parse_invite(invite_str)
            ip = invite["ip"]
            port = invite["port"]
            pubkey = invite["pubkey"]
        except Exception as e:
            self.notify("Invalid Invite Code", severity="error")
            return
        
        if pubkey == self.pub_bytes:
            self.notify("You can't connect to yourself!", severity="error")
            return
        
        self.is_connected = True
        chat_box.write(f"[yellow]System: Connecting to {ip}:{port}[/yellow]")
        nick = self.query_one("#nick-input").value.strip() or "User"

        try:
            reader, writer = await asyncio.open_connection(ip, port)

            proto = NoiseConnection.from_name(b"Noise_XK_25519_ChaChaPoly_SHA256")
            proto.set_as_initiator()
            proto.set_keypair_from_private_bytes(Keypair.STATIC, self.priv_bytes)
            proto.set_keypair_from_public_bytes(Keypair.REMOTE_STATIC, pubkey)
            proto.start_handshake()

            ciphertext1 = proto.write_message()
            await send_msg(writer, ciphertext1)

            ciphertext2 = await recv_msg(reader)
            payload = proto.read_message(ciphertext2)

            ciphertext3 = proto.write_message(payload=nick.encode())
            await send_msg(writer, ciphertext3)

            assert proto.handshake_finished

            self.noise = proto
            self.reader = reader
            self.writer = writer
            self.peer_name = payload.decode(errors='ignore') or 'Anonymous'

            chat_box.write("[green]System: Secure Tunnel Established.[/green]")
            
            asyncio.create_task(self.read_loop())
        
        except Exception as e:
            self.is_connected = False
            self.notify(str(e), severity='error')

    async def send_chat_message(self):
        msg_input = self.query_one('#msg-input', Input)
        msg_text = msg_input.value.strip()
        if not msg_text or not self.is_connected or not self.writer:
            return
        
        chat_box = self.query_one('#chat-box', RichLog)

        nick = self.query_one('#nick-input').value.strip() or "User"

        try:
            ciphertext = self.noise.encrypt(msg_text.encode())
            await send_msg(self.writer, ciphertext)
            chat_box.write(f"[blue]{nick}:[/blue] {msg_text}")
            msg_input.value = ""
        except Exception as e:
            chat_box.write(f"[red]System: {e}[/red]")
            chat_box.write(f"[red]System: Disconnecting.[/red]")
            self.notify(str(e), title="Error", severity="error")
            await self.disconnect()

    async def read_loop(self):
        chat_box = self.query_one('#chat-box', RichLog)
        try:
            while self.is_connected and self.reader:
                ciphertext = await recv_msg(self.reader)
                if not ciphertext: break
                plaintext = self.noise.decrypt(ciphertext)
                msg_text = plaintext.decode(errors='ignore')
                chat_box.write(f"[magenta]{self.peer_name}:[/magenta] {msg_text}")
        except asyncio.IncompleteReadError:
            chat_box.write(f"[yellow]{self.peer_name} disconnected.[/yellow]")
        except Exception as e:
            chat_box.write(f"[red]System: {e}[/red]")
            self.notify(str(e), title="Error", severity="error")
        finally:
            chat_box.write(f"[red]System: Disconnecting.[/red]")
            await self.disconnect()

    async def disconnect(self):
        if not self.is_connected: return

        self.is_connected = False

        try:
            chat_box = self.query_one('#chat-box', RichLog)
            chat_box.write(f"[yellow]System: Session closed.[/yellow]")
        except: pass

        if self.writer:
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except: pass
        
        self.reader = None
        self.writer = None
        self.noise = None

    async def on_unmount(self) -> None:
        await self.disconnect()
        if self.server:
            self.server.close()
            await self.server.wait_closed()



def main():
    app = ChaTTY()
    app.run()


if __name__ == "__main__":
    main()
