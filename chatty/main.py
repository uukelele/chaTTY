import os, random, json, asyncio

from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCDataChannel

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Label, Input, Button, RichLog
from textual.reactive import reactive
from rich.text import Text

from .network import encode_sdp, decode_sdp

STUN_SERVER = RTCIceServer(urls=["stun:stun.l.google.com:19302"])

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

    .section-title {
        color: $secondary;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 1;
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

    .copy-container {
        layout: horizontal;
        height: auto;
        margin-bottom: 1;
    }

    .readonly-output {
        width: 70%;
    }

    .copy-btn {
        width: 30%;
        margin: 0;
    }
    """

    is_connected = reactive(False)
    peer_name = reactive("Anonymous")

    theme = "catppuccin-frappe"

    channel: RTCDataChannel
    pc: RTCPeerConnection

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.pc = None
        self.channel = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Horizontal(
            Vertical(
                Label("Profile", classes="panel-title"),

                Label("Nickname:", classes="field-label"),
                Input(value=os.getenv("USER", f"User_{random.randint(1000, 9999)}"), id="nick-input", placeholder="Anonymous"),

                Label("Host Chat", classes="section-title"),
                Label("Invite Code:", classes="field-label"),
                Horizontal(
                    Input("Generating...", id="host-invite-output", disabled=True, classes="readonly-output"),
                    Button("Copy", variant="primary", id="copy-host-invite-btn", classes="copy-btn"),
                    id="invite-container", classes="copy-container"
                ),
                Label("Peer Answer:", classes="field-label"),
                Input(placeholder="Paste here...", id="host-answer-input"),
                Button("Connect Host", variant="success", id="host-connect-btn"),

                Label("Join Chat", classes="section-title"),
                Label("Peer Invite:", classes="field-label"),
                Input(placeholder="Paste here...", id="join-invite-input"),
                Button("Generate Answer", variant="primary", id="join-generate-btn"),
                Label("Your Answer (Send to Host):", classes="field-label"),
                Horizontal(
                    Input(placeholder="Waiting...", id="join-answer-output", disabled=True, classes="readonly-output"),
                    Button("Copy", variant="primary", id="copy-answer-output-btn", classes="copy-btn"),
                    id="answer-container", classes="copy-container",
                ),

                id="left-panel",
            ),

            Vertical(
                Label("Messages", classes="panel-title"),

                Vertical(
                    Label("Connect to a Host or wait for a connection.", id="placeholder-text"),
                    id="connect-area",
                ),

                Vertical(
                    RichLog(id="chat-box", wrap=True),

                    Horizontal(
                        Input(placeholder="Start typing...", id="msg-input"),
                        Button("Send", variant="success", id="send-btn", classes="small-btn"),
                        Button("Disconnect", variant="error", id="disconnect-btn", classes="small-btn"),

                        id="chat-input-container",
                    ),

                    id="chat-area",
                ),

                id="right-panel"
            )
        )
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one('#chat-area').display = False

        self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[STUN_SERVER]))

        self.channel = self.pc.createDataChannel('chat')
        self.setup_channel_events(self.channel)

        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)

        asyncio.create_task(self.show_invite())

    def watch_is_connected(self, is_connected: bool) -> None:
        try:
            self.query_one('#connect-area').display = not is_connected
            self.query_one('#chat-area').display = is_connected
        except: pass

    async def show_invite(self):
        await asyncio.sleep(2) # wait for webrtc to map ports
        invite_str = encode_sdp(self.pc.localDescription)
        self.query_one('#host-invite-output').value = invite_str

    def setup_channel_events(self, channel: RTCDataChannel):
        @channel.on('open')
        async def on_open():
            self.is_connected = True
            nick = self.query_one('#nick-input').value.strip() or "Anonymous"
            channel.send(json.dumps({'type': 'init', 'nick': nick}))

            self.write_log("[green]System: Tunnel Established.[/green]")

        @channel.on('close')
        async def on_close():
            self.is_connected = False
            try: self.write_log("[yellow]System: Connection closed.[/yellow]")
            except: pass

        @channel.on('message')
        async def on_message(message):
            data = json.loads(message)
            if data.get('type') == 'init':
                self.peer_name = data.get('nick', 'Anonymous')
                self.write_log(f"[yellow]{self.peer_name} has joined the chat.[/yellow]")
            elif data.get('type') == 'chat':
                self.write_log(f"[magenta]{self.peer_name}:[/magenta] {data.get('text', '<empty message>')}")

        if channel.readyState == 'open':
            asyncio.create_task(on_open())

    def write_log(self, text: str):
        self.query_one('#chat-box', RichLog).write(Text.from_markup(text), animate=True)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if  event.button.id == 'host-connect-btn':
            ansr = self.query_one('#host-answer-input').value.strip()
            if ansr:
                try:
                    ansr_sdp = decode_sdp(ansr)
                    await self.pc.setRemoteDescription(ansr_sdp)
                except Exception as e:
                    self.notify(str(e), severity="error")

        elif event.button.id == 'join-generate-btn':
            invite_string = self.query_one('#join-invite-input').value.strip()
            if invite_string:
                try:
                    await self.pc.close()
                    self.pc = RTCPeerConnection(RTCConfiguration(iceServers=[STUN_SERVER]))

                    @self.pc.on('datachannel')
                    async def on_datachannel(channel):
                        self.channel = channel
                        self.setup_channel_events(channel)

                    offer_sdp = decode_sdp(invite_string)
                    await self.pc.setRemoteDescription(offer_sdp)

                    answer = await self.pc.createAnswer()
                    await self.pc.setLocalDescription(answer)

                    self.query_one('#join-answer-output').value = 'Generating...'

                    await asyncio.sleep(2)
                    ansr = encode_sdp(self.pc.localDescription)
                    self.query_one('#join-answer-output').value = ansr
                    self.notify("Answer Generated! Send to host.", severity="information")
                
                except Exception as e:
                    self.notify("Invalid Invite Code", severity="error")


        elif event.button.id == 'send-btn':
            await self.send_chat_message()
        elif event.button.id == 'disconnect-btn':
            await self.disconnect()
        elif event.button.id == 'copy-host-invite-btn':
            self.copy_to_clipboard(self.query_one('#host-invite-output').value)
            self.notify("Invite Code Copied!", severity="information")
        elif event.button.id == 'copy-answer-output-btn':
            self.copy_to_clipboard(self.query_one('#join-answer-output').value)
            self.notify("Answer Copied!", severity="information")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "msg-input":
            await self.send_chat_message()

    async def send_chat_message(self):
        msg_input = self.query_one('#msg-input', Input)
        msg_text = msg_input.value.strip()

        if not msg_text or not self.is_connected or not self.channel:
            return
        
        nick = self.query_one('#nick-input').value.strip() or "Anonymous"

        try:
            self.channel.send(json.dumps({"type": "chat", "text": msg_text}))
            self.write_log(f"[blue]{nick}:[/blue] {msg_text}")
            msg_input.value = ""
        except Exception as e:
            self.write_log(f"[red]System: {e}[/red]")
            self.write_log(f"[red]System: Disconnecting.[/red]")
            self.notify(str(e), title="Error", severity="error")

    async def disconnect(self):
        if not self.is_connected: return

        self.is_connected = False

        try: self.write_log(f"[yellow]System: Session closed.[/yellow]")
        except: pass

        if self.pc:
            try: await self.pc.close()
            except: pass

        self.channel = None

    async def on_unmount(self) -> None:
        await self.disconnect()

def main():
    app = ChaTTY()
    app.run()


if __name__ == "__main__":
    main()
