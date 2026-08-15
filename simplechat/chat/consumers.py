import json

from channels.generic.websocket import AsyncWebsocketConsumer

CALL_GROUP = "call_room"

# username -> channel_name for everyone currently on the call. This is a
# plain in-process dict, which matches the InMemoryChannelLayer in
# settings.py: both only work correctly within a single ASGI worker
# process. If you scale to multiple workers, move this into the channel
# layer's group state (or a small Redis hash) instead.
participants = {}


class CallConsumer(AsyncWebsocketConsumer):
    """
    Signaling relay for WebRTC calls. Doesn't touch audio/video itself -
    it just passes SDP offers/answers and ICE candidates between browsers
    so they can set up a direct (mesh) peer-to-peer connection each.

    Client -> server:
      {"type": "signal", "to": "<username>", "data": {...sdp or ice...}}

    Server -> client:
      {"type": "peers", "peers": [...]}          on connect, who's already on the call
      {"type": "peer-joined", "username": "..."} someone else joined
      {"type": "peer-left", "username": "..."}   someone else left
      {"type": "signal", "from": "...", "data": {...}}  relayed signal
    """

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close()
            return

        self.username = user.username
        await self.channel_layer.group_add(CALL_GROUP, self.channel_name)
        await self.accept()

        # Snapshot who's already here, then register ourselves. The
        # newcomer is responsible for initiating the WebRTC offer to
        # each existing peer, so send this list only to them.
        existing = [u for u in participants if u != self.username]
        participants[self.username] = self.channel_name

        await self.send(text_data=json.dumps({"type": "peers", "peers": existing}))
        await self.channel_layer.group_send(
            CALL_GROUP,
            {
                "type": "call.event",
                "event": "peer-joined",
                "username": self.username,
                "exclude": self.channel_name,
            },
        )

    async def disconnect(self, close_code):
        if getattr(self, "username", None) and participants.get(self.username) == self.channel_name:
            del participants[self.username]
            await self.channel_layer.group_send(
                CALL_GROUP,
                {
                    "type": "call.event",
                    "event": "peer-left",
                    "username": self.username,
                    "exclude": self.channel_name,
                },
            )
        await self.channel_layer.group_discard(CALL_GROUP, self.channel_name)

    async def receive(self, text_data):
        try:
            payload = json.loads(text_data)
        except (TypeError, ValueError):
            return

        if payload.get("type") != "signal":
            return

        target_channel = participants.get(payload.get("to"))
        if not target_channel:
            return

        await self.channel_layer.send(
            target_channel,
            {
                "type": "call.signal",
                "from": self.username,
                "data": payload.get("data"),
            },
        )

    # --- handlers for messages sent via the channel layer (group_send / send) ---

    async def call_event(self, event):
        if event.get("exclude") == self.channel_name:
            return
        await self.send(text_data=json.dumps({
            "type": event["event"],
            "username": event["username"],
        }))

    async def call_signal(self, event):
        await self.send(text_data=json.dumps({
            "type": "signal",
            "from": event["from"],
            "data": event["data"],
        }))
