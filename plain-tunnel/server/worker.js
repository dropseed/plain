export default {
  async fetch(request, env, _context) {
    const url = new URL(request.url);
    let subdomain = null;

    // Development environment handling
    if (env.LOCALHOST_DEV === "true") {
      subdomain = "<dev>";
    } else {
      // Redirect all http requests to https
      // (doing this in a Cloudflare rule breaks ws connections...)
      if (url.protocol === "http:") {
        return Response.redirect(`https://${url.hostname}${url.pathname}`, 301);
      }

      const hostnameParts = url.hostname.split(".");

      // At this point we know we only have a single subdomain
      // because Cloudfflare has redirected the ones we protect,
      // and we can't have a subdomain of a subdomain at the DNS level.
      subdomain = hostnameParts[0];
    }

    console.debug(`Handling request for subdomain: ${subdomain}`);

    // Each subdomain corresponds to a unique client object
    const objectId = env.TUNNEL_NAMESPACE.idFromName(subdomain);
    const clientObject = env.TUNNEL_NAMESPACE.get(objectId);
    return clientObject.fetch(request);
  },
};

export class Tunnel {
  constructor(_state, _env) {
    this.clientSocket = null;
    this.pendingRequests = new Map();
    this.heartbeatInterval = null;
    this.heartbeatTimeout = null;
  }

  async fetch(request) {
    if (request.headers.get("Upgrade") === "websocket") {
      console.debug("Received WebSocket upgrade request");
      return this.handleWebSocket();
    }
    console.debug("Received HTTP request");
    return this.handleHttpRequest(request);
  }

  startHeartbeat() {
    this.stopHeartbeat();
    this.heartbeatInterval = setInterval(() => {
      if (this.clientSocket) {
        try {
          console.debug("Sent heartbeat ping");
          this.clientSocket.send(JSON.stringify({ type: "ping" }));
          this.heartbeatTimeout = setTimeout(() => {
            console.warn("Heartbeat pong not received within 30s, closing connection");
            if (this.clientSocket) {
              this.clientSocket.close(1000, "Heartbeat timeout");
              this.clientSocket = null;
            }
          }, 30000);
        } catch (e) {
          console.error("Failed to send heartbeat ping:", e);
          this.stopHeartbeat();
          this.clientSocket = null;
        }
      }
    }, 15000);
  }

  stopHeartbeat() {
    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
    if (this.heartbeatTimeout) {
      clearTimeout(this.heartbeatTimeout);
      this.heartbeatTimeout = null;
    }
  }

  resetHeartbeatTimeout() {
    if (this.heartbeatTimeout) {
      clearTimeout(this.heartbeatTimeout);
      this.heartbeatTimeout = null;
    }
  }

  handleWebSocket() {
    const [client, server] = Object.values(new WebSocketPair());

    if (this.clientSocket) {
      console.info("Closing existing WebSocket connection");
      this.clientSocket.close(1000, "Another client connected");

      // Resolve any pending requests targeting the old socket with 503
      for (const [id, pending] of this.pendingRequests) {
        console.info(`Resolving pending request ${id} due to reconnection`);
        pending.resolve(new Response("Client reconnecting", { status: 503 }));
        pending.cleanup();
      }
    }

    this.clientSocket = server;
    this.clientSocket.accept();

    console.info("WebSocket connection established");

    server.addEventListener("message", (event) => {
      if (typeof event.data === "string") {
        const data = JSON.parse(event.data);
        switch (data.type) {
          case "pong":
            console.debug("Received heartbeat pong");
            this.resetHeartbeatTimeout();
            break;
          case "response":
            console.info("Received response metadata from client");
            this.handleResponseMetadata(data);
            break;
          default:
            console.warn(`Received unknown message type: ${data.type}`);
        }
      } else {
        console.info("Received binary data from client");
        this.handleResponseBodyChunk(event.data);
      }
    });

    server.addEventListener("close", (event) => {
      console.info(`WebSocket connection closed: ${event.reason}`);
      if (this.clientSocket === server) {
        this.stopHeartbeat();
        this.clientSocket = null;
      }
    });

    server.addEventListener("error", (error) => {
      console.error("WebSocket error:", error);
    });

    this.startHeartbeat();

    return new Response(null, { status: 101, webSocket: client });
  }

  handleResponseMetadata(data) {
    const { id, has_body, totalBodyChunks } = data;
    const pendingRequest = this.pendingRequests.get(id);
    if (pendingRequest) {
      console.info(`Received response metadata for ID: ${id}, has_body: ${has_body}`);
      pendingRequest.responseMetadata = data;
      pendingRequest.has_body = has_body;
      pendingRequest.totalBodyChunks = totalBodyChunks || 0;
      this.checkIfResponseComplete(id);
    } else {
      console.warn(`Received metadata for unknown or completed request ID: ${id}`);
    }
  }

  handleResponseBodyChunk(chunkData) {
    const idDecoder = new TextDecoder();
    const idBytes = chunkData.slice(0, 36);
    const id = idDecoder.decode(idBytes);

    const chunkIndexArray = new Uint32Array(chunkData.slice(36, 40));
    const chunkIndex = chunkIndexArray[0];

    const totalChunksArray = new Uint32Array(chunkData.slice(40, 44));
    const totalChunks = totalChunksArray[0];

    const bodyChunk = chunkData.slice(44);

    const pendingRequest = this.pendingRequests.get(id);
    if (pendingRequest) {
      console.info(`Received body chunk ${chunkIndex + 1}/${totalChunks} for ID: ${id}`);

      if (!pendingRequest.bodyChunks) {
        pendingRequest.bodyChunks = {};
        pendingRequest.totalBodyChunks = totalChunks;
      }

      pendingRequest.bodyChunks[chunkIndex] = bodyChunk;

      this.checkIfResponseComplete(id);
    } else {
      console.warn(`Received body chunk for unknown or completed request ID: ${id}`);
    }
  }

  checkIfResponseComplete(id) {
    const pendingRequest = this.pendingRequests.get(id);
    if (!pendingRequest) return;

    const { responseMetadata, has_body, totalBodyChunks, bodyChunks } = pendingRequest;

    const allChunksReceived = has_body
      ? bodyChunks && Object.keys(bodyChunks).length === totalBodyChunks
      : true;

    if (responseMetadata && allChunksReceived) {
      console.debug(`Response complete for ID: ${id}`);
      const { status, headers } = responseMetadata;

      let responseBody = null;
      if (has_body) {
        const chunksArray = [];
        for (let i = 0; i < totalBodyChunks; i++) {
          if (bodyChunks[i] === undefined) {
            console.error(`Missing chunk ${i + 1}/${totalBodyChunks} for request ID: ${id}`);
            return;
          }
          chunksArray.push(new Uint8Array(bodyChunks[i]));
        }
        const totalSize = chunksArray.reduce((acc, chunk) => acc + chunk.byteLength, 0);
        responseBody = new Uint8Array(totalSize);
        let offset = 0;
        for (const chunk of chunksArray) {
          responseBody.set(chunk, offset);
          offset += chunk.byteLength;
        }
      }

      pendingRequest.resolve(new Response(responseBody, { status, headers }));

      pendingRequest.cleanup();
    }
  }

  async handleHttpRequest(request) {
    if (!this.clientSocket) {
      return new Response("No client connected", { status: 503 });
    }

    const id = crypto.randomUUID();
    console.debug(`Processing HTTP request with ID: ${id}`);

    const requestBodyArrayBuffer = await request.arrayBuffer();
    const has_body = requestBodyArrayBuffer.byteLength > 0;

    const maxChunkSize = 1_000_000;
    const totalChunks = has_body ? Math.ceil(requestBodyArrayBuffer.byteLength / maxChunkSize) : 0;

    const metadata = {
      type: "request",
      id,
      url: request.url,
      method: request.method,
      headers: Object.fromEntries(request.headers),
      has_body,
      totalBodyChunks: totalChunks,
    };

    const metadataString = JSON.stringify(metadata);

    const socket = this.clientSocket;

    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        console.debug(`Request with ID ${id} timed out`);
        cleanup();
        resolve(new Response("Request timed out", { status: 504 }));
      }, 30000); // 30-second timeout

      const cleanup = () => {
        clearTimeout(timeout);
        this.pendingRequests.delete(id);
        socket.removeEventListener("close", onClose);
        socket.removeEventListener("error", onError);
      };

      this.pendingRequests.set(id, {
        resolve,
        cleanup,
        responseMetadata: null,
        has_body: null,
        totalBodyChunks: null,
        bodyChunks: null,
      });

      const onClose = () => {
        console.debug("WebSocket connection closed while waiting for response");
        cleanup();
        resolve(new Response("Client disconnected", { status: 503 }));
      };

      const onError = (error) => {
        console.error("WebSocket error:", error);
        cleanup();
        resolve(new Response("WebSocket error", { status: 500 }));
      };

      socket.addEventListener("close", onClose);
      socket.addEventListener("error", onError);

      console.debug(`Sending request metadata for ID: ${id}, has_body: ${has_body}`);
      socket.send(metadataString);

      if (has_body) {
        console.debug(`Sending request body for ID: ${id}`);

        const idBytes = new TextEncoder().encode(id);
        const idLength = idBytes.length;

        for (let i = 0; i < totalChunks; i++) {
          const chunkStart = i * maxChunkSize;
          const chunkEnd = Math.min(chunkStart + maxChunkSize, requestBodyArrayBuffer.byteLength);
          const bodyChunk = requestBodyArrayBuffer.slice(chunkStart, chunkEnd);

          const messageSize = 4 + idLength + 4 + 4 + bodyChunk.byteLength;
          const messageBuffer = new Uint8Array(messageSize);
          let offset = 0;

          messageBuffer.set(new Uint8Array(new Uint32Array([idLength]).buffer), offset);
          offset += 4;

          messageBuffer.set(idBytes, offset);
          offset += idLength;

          messageBuffer.set(new Uint8Array(new Uint32Array([i]).buffer), offset);
          offset += 4;

          messageBuffer.set(new Uint8Array(new Uint32Array([totalChunks]).buffer), offset);
          offset += 4;

          messageBuffer.set(new Uint8Array(bodyChunk), offset);

          socket.send(messageBuffer.buffer);
          console.debug(`Sent body chunk ${i + 1}/${totalChunks} for ID: ${id}`);
        }
      }
    });
  }
}
