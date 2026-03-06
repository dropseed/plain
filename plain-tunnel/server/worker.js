import { errorResponse } from "./errors.js";

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

// Bump when making breaking protocol changes.
// Clients with a version below this will be rejected.
const MIN_PROTOCOL_VERSION = 3;

// Response body chunks use a fixed-length UUID (36 bytes) as the ID prefix.
const UUID_BYTE_LENGTH = 36;

export class Tunnel {
  constructor(_state, _env) {
    this.clientSocket = null;
    this.pendingRequests = new Map();
    this.proxiedWebSockets = new Map();
    this.heartbeatInterval = null;
    this.heartbeatTimeout = null;
  }

  async fetch(request) {
    if (request.headers.get("Upgrade") === "websocket") {
      const url = new URL(request.url);
      if (url.pathname === "/__tunnel__") {
        console.debug("Received tunnel client WebSocket upgrade");
        return this.handleWebSocket(request);
      }
      console.debug("Received browser WebSocket upgrade");
      return this.handleWebSocketProxy(request);
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

  handleWebSocket(request) {
    const url = new URL(request.url);
    const clientVersion = parseInt(url.searchParams.get("v") || "0", 10);

    if (clientVersion < MIN_PROTOCOL_VERSION) {
      return errorResponse(
        426,
        "Upgrade Required",
        `Client protocol version ${clientVersion} is too old (minimum: ${MIN_PROTOCOL_VERSION}). Please upgrade: uv sync --upgrade-package plain.tunnel`,
        request.headers.get("Accept"),
      );
    }

    const [client, server] = Object.values(new WebSocketPair());

    if (this.clientSocket) {
      console.info("Closing existing WebSocket connection");
      this.clientSocket.close(1000, "Another client connected");

      // Resolve any pending requests targeting the old socket with 503
      for (const [id, pending] of this.pendingRequests) {
        console.info(`Resolving pending request ${id} due to reconnection`);
        if (pending.streaming && pending.streamWriter) {
          pending.streamWriter.abort(new Error("Client reconnecting"));
        } else {
          pending.resolve(
            errorResponse(
              503,
              "Client Reconnecting",
              "The tunnel client is reconnecting. Please try again in a moment.",
              pending.accept,
            ),
          );
        }
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
          case "stream-start":
            console.info("Received stream-start from client");
            this.handleStreamStart(data);
            break;
          case "stream-end":
            console.info("Received stream-end from client");
            this.handleStreamEnd(data);
            break;
          case "stream-error":
            console.info("Received stream-error from client");
            this.handleStreamError(data);
            break;
          case "ws-message":
            this.handleProxiedWsMessage(data);
            break;
          case "ws-close":
            this.handleProxiedWsClose(data);
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

        // Close all proxied WebSockets
        for (const [id, browserSocket] of this.proxiedWebSockets) {
          console.info(`Closing proxied WebSocket ${id} due to tunnel client disconnect`);
          try {
            browserSocket.close(1001, "Tunnel client disconnected");
          } catch {
            /* ignore */
          }
        }
        this.proxiedWebSockets.clear();

        // Abort any active streaming requests and reject pending buffered ones
        for (const [id, pending] of this.pendingRequests) {
          if (pending.streaming && pending.streamWriter) {
            console.info(`Aborting stream for request ${id} due to WebSocket close`);
            pending.streamWriter.abort(new Error("Client disconnected"));
          } else if (!pending.streaming) {
            pending.resolve(
              errorResponse(
                503,
                "Client Disconnected",
                "The tunnel client disconnected. Make sure your local dev server and tunnel client are running.",
                pending.accept,
              ),
            );
          }
          pending.cleanup();
        }
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

  handleStreamStart(data) {
    const { id, status, headers } = data;
    const pendingRequest = this.pendingRequests.get(id);
    if (!pendingRequest) {
      console.warn(`Received stream-start for unknown request ID: ${id}`);
      return;
    }

    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();

    pendingRequest.streaming = true;
    pendingRequest.streamWriter = writer;

    // Clear the request timeout since streaming can last indefinitely
    if (pendingRequest.timeoutId) {
      clearTimeout(pendingRequest.timeoutId);
      pendingRequest.timeoutId = null;
    }

    // Resolve the HTTP response immediately with the readable stream
    pendingRequest.resolve(new Response(readable, { status, headers }));
  }

  handleStreamEnd(data) {
    const { id } = data;
    const pendingRequest = this.pendingRequests.get(id);
    if (!pendingRequest || !pendingRequest.streaming) {
      console.warn(`Received stream-end for unknown or non-streaming request ID: ${id}`);
      return;
    }

    console.debug(`Stream ended for request ID: ${id}`);
    pendingRequest.streamWriter.close().catch(() => {});
    pendingRequest.cleanup();
  }

  handleStreamError(data) {
    const { id, error } = data;
    const pendingRequest = this.pendingRequests.get(id);
    if (!pendingRequest || !pendingRequest.streaming) {
      console.warn(`Received stream-error for unknown or non-streaming request ID: ${id}`);
      return;
    }

    console.error(`Stream error for request ID: ${id}: ${error}`);
    pendingRequest.streamWriter.abort(new Error(error || "Stream error")).catch(() => {});
    pendingRequest.cleanup();
  }

  handleResponseBodyChunk(chunkData) {
    const id = new TextDecoder().decode(chunkData.slice(0, UUID_BYTE_LENGTH));
    const pendingRequest = this.pendingRequests.get(id);

    if (!pendingRequest) {
      console.warn(`Received body chunk for unknown or completed request ID: ${id}`);
      return;
    }

    if (pendingRequest.streaming) {
      // Streaming mode: remaining bytes after ID are the body data
      const bodyData = chunkData.slice(UUID_BYTE_LENGTH);
      pendingRequest.streamWriter.write(new Uint8Array(bodyData)).catch(() => {
        // Write failed — browser likely disconnected
        console.info(`Browser disconnected from stream for request ID: ${id}`);
        if (this.clientSocket) {
          try {
            this.clientSocket.send(JSON.stringify({ type: "stream-cancel", id }));
          } catch (e) {
            console.error("Failed to send stream-cancel:", e);
          }
        }
        pendingRequest.cleanup();
      });
    } else {
      // Buffered mode: parse chunk_index and total_chunks after ID
      const headerEnd = UUID_BYTE_LENGTH + 8;
      const [chunkIndex, totalChunks] = new Uint32Array(
        chunkData.slice(UUID_BYTE_LENGTH, headerEnd),
      );
      const bodyChunk = chunkData.slice(headerEnd);

      console.info(`Received body chunk ${chunkIndex + 1}/${totalChunks} for ID: ${id}`);
      pendingRequest.bodyChunks[chunkIndex] = bodyChunk;
      this.checkIfResponseComplete(id);
    }
  }

  checkIfResponseComplete(id) {
    const pendingRequest = this.pendingRequests.get(id);
    if (!pendingRequest) return;

    const { responseMetadata, has_body, totalBodyChunks, bodyChunks } = pendingRequest;

    const allChunksReceived = !has_body || Object.keys(bodyChunks).length === totalBodyChunks;

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

      // If the client returned a 502 with no body, it means it couldn't
      // connect to the local server. Generate a proper error page.
      if (status === 502 && !has_body) {
        pendingRequest.resolve(
          errorResponse(
            502,
            "Bad Gateway",
            "Could not connect to the local dev server. Make sure it is running.",
            pendingRequest.accept,
          ),
        );
      } else {
        pendingRequest.resolve(new Response(responseBody, { status, headers }));
      }

      pendingRequest.cleanup();
    }
  }

  handleWebSocketProxy(request) {
    const accept = request.headers.get("Accept");

    if (!this.clientSocket) {
      return errorResponse(
        503,
        "No Client Connected",
        "No tunnel client is connected to this subdomain.",
        accept,
      );
    }

    const id = crypto.randomUUID();
    const [client, server] = Object.values(new WebSocketPair());

    server.accept();
    this.proxiedWebSockets.set(id, server);

    // Tell the tunnel client to open a WebSocket to the local server
    this.clientSocket.send(
      JSON.stringify({
        type: "ws-open",
        id,
        url: request.url,
        headers: Object.fromEntries(request.headers),
      }),
    );

    server.addEventListener("message", (event) => {
      if (!this.clientSocket) return;
      try {
        if (typeof event.data === "string") {
          this.clientSocket.send(JSON.stringify({ type: "ws-message", id, data: event.data }));
        } else {
          // Binary messages are base64-encoded in JSON
          const bytes = new Uint8Array(event.data);
          let binary = "";
          for (let i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
          }
          this.clientSocket.send(
            JSON.stringify({ type: "ws-message", id, data: btoa(binary), binary: true }),
          );
        }
      } catch (e) {
        console.error(`Failed to forward browser WS message for ${id}:`, e);
      }
    });

    server.addEventListener("close", () => {
      this.proxiedWebSockets.delete(id);
      if (this.clientSocket) {
        try {
          this.clientSocket.send(JSON.stringify({ type: "ws-close", id }));
        } catch {
          /* ignore */
        }
      }
    });

    return new Response(null, { status: 101, webSocket: client });
  }

  handleProxiedWsMessage(data) {
    const { id } = data;
    const browserSocket = this.proxiedWebSockets.get(id);
    if (!browserSocket) {
      console.warn(`Received ws-message for unknown proxied WebSocket: ${id}`);
      return;
    }
    try {
      if (data.binary) {
        const binaryStr = atob(data.data);
        const bytes = new Uint8Array(binaryStr.length);
        for (let i = 0; i < binaryStr.length; i++) {
          bytes[i] = binaryStr.charCodeAt(i);
        }
        browserSocket.send(bytes.buffer);
      } else {
        browserSocket.send(data.data);
      }
    } catch (e) {
      console.error(`Failed to send to browser WebSocket ${id}:`, e);
      this.proxiedWebSockets.delete(id);
    }
  }

  handleProxiedWsClose(data) {
    const { id, code, reason } = data;
    const browserSocket = this.proxiedWebSockets.get(id);
    if (!browserSocket) return;
    this.proxiedWebSockets.delete(id);
    try {
      browserSocket.close(code || 1000, reason || "");
    } catch {
      /* ignore */
    }
  }

  async handleHttpRequest(request) {
    const accept = request.headers.get("Accept");

    if (!this.clientSocket) {
      return errorResponse(
        503,
        "No Client Connected",
        "No tunnel client is connected to this subdomain. Make sure your local dev server and tunnel client are running.",
        accept,
      );
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
      const timeoutId = setTimeout(() => {
        console.debug(`Request with ID ${id} timed out`);
        cleanup();
        resolve(
          errorResponse(
            504,
            "Request Timed Out",
            "The tunnel client did not respond within 30 seconds. Your local server may be slow or unresponsive.",
            accept,
          ),
        );
      }, 30000); // 30-second timeout

      const cleanup = () => {
        if (pendingEntry.timeoutId) {
          clearTimeout(pendingEntry.timeoutId);
        }
        this.pendingRequests.delete(id);
        socket.removeEventListener("close", onClose);
        socket.removeEventListener("error", onError);
      };

      const pendingEntry = {
        resolve,
        cleanup,
        accept,
        timeoutId,
        responseMetadata: null,
        has_body: null,
        totalBodyChunks: 0,
        bodyChunks: {},
        streaming: false,
        streamWriter: null,
      };

      this.pendingRequests.set(id, pendingEntry);

      const onClose = () => {
        console.debug("WebSocket connection closed while waiting for response");
        if (pendingEntry.streaming && pendingEntry.streamWriter) {
          pendingEntry.streamWriter.abort(new Error("Client disconnected"));
        } else if (!pendingEntry.streaming) {
          resolve(
            errorResponse(
              503,
              "Client Disconnected",
              "The tunnel client disconnected while processing your request. Make sure your local dev server and tunnel client are running.",
              accept,
            ),
          );
        }
        cleanup();
      };

      const onError = (error) => {
        console.error("WebSocket error:", error);
        if (pendingEntry.streaming && pendingEntry.streamWriter) {
          pendingEntry.streamWriter.abort(new Error("WebSocket error"));
        } else if (!pendingEntry.streaming) {
          resolve(
            errorResponse(
              500,
              "Tunnel Error",
              "An unexpected error occurred in the tunnel connection.",
              accept,
            ),
          );
        }
        cleanup();
      };

      socket.addEventListener("close", onClose);
      socket.addEventListener("error", onError);

      console.debug(`Sending request metadata for ID: ${id}, has_body: ${has_body}`);
      socket.send(metadataString);

      if (has_body) {
        console.debug(`Sending request body for ID: ${id}`);

        const idBytes = new TextEncoder().encode(id);
        const idLength = idBytes.length;
        const headerSize = 4 + idLength + 8;

        for (let i = 0; i < totalChunks; i++) {
          const chunkStart = i * maxChunkSize;
          const chunkEnd = Math.min(chunkStart + maxChunkSize, requestBodyArrayBuffer.byteLength);
          const bodyChunk = new Uint8Array(requestBodyArrayBuffer.slice(chunkStart, chunkEnd));

          const message = new Uint8Array(headerSize + bodyChunk.byteLength);
          const view = new DataView(message.buffer);
          let offset = 0;

          view.setUint32(offset, idLength, true);
          offset += 4;
          message.set(idBytes, offset);
          offset += idLength;
          view.setUint32(offset, i, true);
          offset += 4;
          view.setUint32(offset, totalChunks, true);
          offset += 4;
          message.set(bodyChunk, offset);

          socket.send(message.buffer);
          console.debug(`Sent body chunk ${i + 1}/${totalChunks} for ID: ${id}`);
        }
      }
    });
  }
}
