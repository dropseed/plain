/**
 * Portal relay server.
 *
 * Pairs two WebSocket connections by a shared portal code and forwards
 * messages between them. The relay never sees plaintext — both sides
 * use SPAKE2 + NaCl for E2E encryption, and the relay just passes
 * opaque bytes.
 *
 * Architecture:
 *   - Each portal code maps to one Durable Object instance.
 *   - The first connection (side=start) waits for the second (side=connect).
 *   - Once paired, SPAKE2 messages are exchanged, then all subsequent
 *     messages are forwarded directly between the two sockets.
 *   - When either side disconnects, the other is notified and the
 *     Durable Object cleans up.
 */

// Protocol version — reject clients below this.
const MIN_PROTOCOL_VERSION = 1;

export default {
  async fetch(request, env, _context) {
    const url = new URL(request.url);

    // Only WebSocket upgrades to /__portal__
    if (request.headers.get("Upgrade") !== "websocket") {
      return new Response("Portal relay accepts WebSocket connections only.", {
        status: 426,
        headers: { "Content-Type": "text/plain" },
      });
    }

    if (url.pathname !== "/__portal__") {
      return new Response("Not found", { status: 404 });
    }

    const channel = url.searchParams.get("channel");
    if (!channel) {
      return new Response("Missing 'channel' parameter", { status: 400 });
    }

    const version = parseInt(url.searchParams.get("v") || "0", 10);
    if (version < MIN_PROTOCOL_VERSION) {
      return new Response(
        `Client protocol version ${version} is too old (minimum: ${MIN_PROTOCOL_VERSION}). Please upgrade: uv sync --upgrade-package plain.portal`,
        { status: 426 },
      );
    }

    const side = url.searchParams.get("side");
    if (side !== "start" && side !== "connect") {
      return new Response("'side' must be 'start' or 'connect'", { status: 400 });
    }

    // Each channel maps to a unique Durable Object
    const objectId = env.PORTAL_NAMESPACE.idFromName(channel);
    const portal = env.PORTAL_NAMESPACE.get(objectId);

    // Forward to the Durable Object, passing side info via header
    const newHeaders = new Headers(request.headers);
    newHeaders.set("X-Portal-Side", side);
    const newRequest = new Request(request.url, {
      headers: newHeaders,
      method: request.method,
    });

    return portal.fetch(newRequest);
  },
};

export class Portal {
  constructor(_state, _env) {
    // The two sides of the portal
    this.startSocket = null; // side=start (remote/production)
    this.connectSocket = null; // side=connect (local/developer)

    // SPAKE2 messages buffered until both sides are present
    this.startSpakeMsg = null;
    this.connectSpakeMsg = null;

    // Whether the SPAKE2 exchange is complete (both sides have each other's messages)
    this.paired = false;

    // Heartbeat for idle cleanup
    this.idleTimeout = null;
    this.resetIdleTimeout();
  }

  resetIdleTimeout() {
    if (this.idleTimeout) {
      clearTimeout(this.idleTimeout);
    }
    // Clean up after 35 minutes of no messages (slightly longer than client's 30-min idle timeout)
    this.idleTimeout = setTimeout(
      () => {
        this.closeAll("Idle timeout");
      },
      35 * 60 * 1000,
    );
  }

  closeAll(reason) {
    for (const socket of [this.startSocket, this.connectSocket]) {
      if (socket) {
        try {
          socket.close(1000, reason);
        } catch {
          /* ignore */
        }
      }
    }
    this.startSocket = null;
    this.connectSocket = null;
    this.paired = false;
    if (this.idleTimeout) {
      clearTimeout(this.idleTimeout);
      this.idleTimeout = null;
    }
  }

  async fetch(request) {
    const side = request.headers.get("X-Portal-Side");

    // Reject if this side is already connected
    if (side === "start" && this.startSocket) {
      return new Response("A 'start' side is already connected for this code.", {
        status: 409,
      });
    }
    if (side === "connect" && this.connectSocket) {
      return new Response("A 'connect' side is already connected for this code.", {
        status: 409,
      });
    }

    const [client, server] = Object.values(new WebSocketPair());
    server.accept();

    if (side === "start") {
      this.startSocket = server;
    } else {
      this.connectSocket = server;
    }

    const peerSocket = () => (side === "start" ? this.connectSocket : this.startSocket);

    server.addEventListener("message", (event) => {
      this.resetIdleTimeout();

      if (!this.paired) {
        // Before pairing: this must be the SPAKE2 message
        if (side === "start") {
          this.startSpakeMsg = event.data;
        } else {
          this.connectSpakeMsg = event.data;
        }
        this.tryExchangeSpake();
        return;
      }

      // After pairing: forward everything to the peer
      const peer = peerSocket();
      if (peer) {
        try {
          peer.send(event.data);
        } catch {
          // Peer gone — close both
          this.closeAll("Peer send failed");
        }
      }
    });

    server.addEventListener("close", () => {
      // Clear this side's state
      if (side === "start") {
        this.startSocket = null;
        this.startSpakeMsg = null;
      } else {
        this.connectSocket = null;
        this.connectSpakeMsg = null;
      }

      // Notify and close the peer
      const peer = peerSocket();
      if (peer) {
        try {
          peer.close(1000, `${side} side disconnected`);
        } catch {
          /* ignore */
        }
      }

      this.paired = false;
    });

    server.addEventListener("error", (err) => {
      console.error(`WebSocket error (${side}):`, err);
    });

    return new Response(null, { status: 101, webSocket: client });
  }

  tryExchangeSpake() {
    // Both sides have sent their SPAKE2 messages — swap them
    if (this.startSpakeMsg && this.connectSpakeMsg) {
      // Send start's message to connect, and vice versa
      if (this.connectSocket) {
        this.connectSocket.send(this.startSpakeMsg);
      }
      if (this.startSocket) {
        this.startSocket.send(this.connectSpakeMsg);
      }

      this.paired = true;
      this.startSpakeMsg = null;
      this.connectSpakeMsg = null;
      console.info("Portal paired — forwarding encrypted messages");
    }
  }
}
