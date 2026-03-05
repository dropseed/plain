from plain.channels import Channel, channel_registry


@channel_registry.register
class EchoChannel(Channel):
    """WebSocket echo channel for conformance testing."""

    path = "/ws-echo/"

    def authorize(self, request):
        return True

    def subscribe(self, request):
        return ["echo"]

    def receive(self, message):
        return message
