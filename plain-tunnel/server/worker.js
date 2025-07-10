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
    // this.state = state;
    // this.env = env;
    this.clientSocket = null;
    this.pendingRequests = new Map();
  }

  async fetch(request) {
    if (request.headers.get("Upgrade") === "websocket") {
      console.debug("Received WebSocket upgrade request");
      return this.handleWebSocket(request);
    }
    console.debug("Received HTTP request");
    return this.handleHttpRequest(request);
  }

  handleWebSocket(_request) {
    const [client, server] = Object.values(new WebSocketPair());

    // Check against reserved subdomains
    // const url = new URL(request.url);
    // const hostnameParts = url.hostname.split(".");
    // const subdomain = hostnameParts[0];
    // const reservedSubdomains = [
    // 	"www",
    // 	"api",
    // 	"app",
    // 	"blog",
    // 	"mail",
    // 	"admin",
    // 	"dashboard",
    // 	// these should be reserved in the API,
    // 	// along with ones that are reserved per
    // ];

    if (this.clientSocket) {
      console.info("Closing existing WebSocket connection");
      this.clientSocket.close(1000, "Another client connected");
    }
    this.clientSocket = server;
    this.clientSocket.accept();

    console.info("WebSocket connection established");

    this.clientSocket.addEventListener("message", (event) => {
      if (typeof event.data === "string") {
        // Handle text message (metadata)
        console.info("Received metadata from client");
        const data = JSON.parse(event.data);
        this.handleResponseMetadata(data);
      } else {
        // Handle binary message (body chunks)
        console.info("Received binary data from client");
        this.handleResponseBodyChunk(event.data);
      }
    });

    this.clientSocket.addEventListener("close", (event) => {
      console.info(`WebSocket connection closed: ${event.reason}`);
      this.clientSocket = null;
    });

    this.clientSocket.addEventListener("error", (error) => {
      console.error("WebSocket error:", error);
    });

    return new Response(null, { status: 101, webSocket: client });
  }

  handleResponseMetadata(data) {
    const { id, has_body, totalBodyChunks } = data;
    const pendingRequest = this.pendingRequests.get(id);
    if (pendingRequest) {
      console.info(
        `Received response metadata for ID: ${id}, has_body: ${has_body}`,
      );
      pendingRequest.responseMetadata = data;
      pendingRequest.has_body = has_body;
      pendingRequest.totalBodyChunks = totalBodyChunks || 0;
      this.checkIfResponseComplete(id);
    } else {
      console.warn(
        `Received metadata for unknown or completed request ID: ${id}`,
      );
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
      console.info(
        `Received body chunk ${chunkIndex + 1}/${totalChunks} for ID: ${id}`,
      );

      if (!pendingRequest.bodyChunks) {
        pendingRequest.bodyChunks = {};
        pendingRequest.totalBodyChunks = totalChunks;
      }

      pendingRequest.bodyChunks[chunkIndex] = bodyChunk;

      this.checkIfResponseComplete(id);
    } else {
      console.warn(
        `Received body chunk for unknown or completed request ID: ${id}`,
      );
    }
  }

  checkIfResponseComplete(id) {
    const pendingRequest = this.pendingRequests.get(id);
    if (!pendingRequest) return;

    const { responseMetadata, has_body, totalBodyChunks, bodyChunks } =
      pendingRequest;

    const allChunksReceived = has_body
      ? bodyChunks && Object.keys(bodyChunks).length === totalBodyChunks
      : true;

    if (responseMetadata && allChunksReceived) {
      console.debug(`Response complete for ID: ${id}`);
      const { status, headers } = responseMetadata;

      let responseBody = null;
      if (has_body) {
        // Concatenate body chunks in order
        const chunksArray = [];
        for (let i = 0; i < totalBodyChunks; i++) {
          if (bodyChunks[i] === undefined) {
            console.error(
              `Missing chunk ${i + 1}/${totalBodyChunks} for request ID: ${id}`,
            );
            return;
          }
          chunksArray.push(new Uint8Array(bodyChunks[i]));
        }
        responseBody = new Uint8Array(
          chunksArray.reduce((acc, chunk) => acc + chunk.byteLength, 0),
        );
        let offset = 0;
        for (const chunk of chunksArray) {
          responseBody.set(chunk, offset);
          offset += chunk.byteLength;
        }
      }

      pendingRequest.resolve(
        new Response(responseBody, {
          status: status,
          headers: headers,
        }),
      );

      // Call cleanup to clear timeout and remove listeners
      pendingRequest.cleanup();
    }
  }

  async handleHttpRequest(request) {
    if (!this.clientSocket) {
      return new Response("No client connected", { status: 503 });
    }

    const id = crypto.randomUUID(); // Use UUID for unique IDs
    console.debug(`Processing HTTP request with ID: ${id}`);

    const requestBodyArrayBuffer = await request.arrayBuffer();
    const has_body = requestBodyArrayBuffer.byteLength > 0;

    // Calculate totalChunks here if has_body is true
    let totalChunks = 0;
    const maxChunkSize = 1000000; // 1,000,000 bytes
    if (has_body) {
      totalChunks = Math.ceil(requestBodyArrayBuffer.byteLength / maxChunkSize);
    }

    const metadata = {
      id,
      url: request.url,
      method: request.method,
      headers: Object.fromEntries(request.headers),
      has_body: has_body,
      totalBodyChunks: totalChunks,
    };

    const metadataString = JSON.stringify(metadata);

    const socket = this.clientSocket;

    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        console.debug(`Request with ID ${id} timed out`);
        cleanup();
        reject(new Response("Request timed out", { status: 504 }));
      }, 30000); // 30-second timeout

      const cleanup = () => {
        clearTimeout(timeout);
        this.pendingRequests.delete(id);

        if (socket) {
          socket.removeEventListener("close", onClose);
          socket.removeEventListener("error", onError);
        }
      };

      this.pendingRequests.set(id, {
        resolve,
        reject,
        cleanup,
        responseMetadata: null,
        has_body: null,
        totalBodyChunks: null,
        bodyChunks: null,
      });

      const onClose = () => {
        console.debug("WebSocket connection closed while waiting for response");
        cleanup();
        reject(new Response("Client disconnected", { status: 503 }));
      };

      const onError = (error) => {
        console.error("WebSocket error:", error);
        cleanup();
        reject(new Response("WebSocket error", { status: 500 }));
      };

      socket.addEventListener("close", onClose);
      socket.addEventListener("error", onError);

      // Send metadata
      console.debug(
        `Sending request metadata for ID: ${id}, has_body: ${has_body}`,
      );
      socket.send(metadataString);

      // Send body if present
      if (has_body) {
        console.debug(`Sending request body for ID: ${id}`);

        const idEncoder = new TextEncoder();
        const idBytes = idEncoder.encode(id);
        const idLength = idBytes.length;

        for (let i = 0; i < totalChunks; i++) {
          const chunkStart = i * maxChunkSize;
          const chunkEnd = Math.min(
            chunkStart + maxChunkSize,
            requestBodyArrayBuffer.byteLength,
          );
          const bodyChunk = requestBodyArrayBuffer.slice(chunkStart, chunkEnd);

          // Prepare the binary message
          const chunkIndexArray = new Uint32Array([i]);
          const totalChunksArray = new Uint32Array([totalChunks]);
          const idLengthArray = new Uint32Array([idLength]);

          // Calculate total message size
          const messageSize =
            4 + // idLengthArray
            idLength +
            4 + // chunkIndexArray
            4 + // totalChunksArray
            bodyChunk.byteLength;

          // Create the message buffer
          const messageBuffer = new Uint8Array(messageSize);
          let offset = 0;

          // Copy idLength
          messageBuffer.set(new Uint8Array(idLengthArray.buffer), offset);
          offset += 4;

          // Copy idBytes
          messageBuffer.set(idBytes, offset);
          offset += idLength;

          // Copy chunkIndex
          messageBuffer.set(new Uint8Array(chunkIndexArray.buffer), offset);
          offset += 4;

          // Copy totalChunks
          messageBuffer.set(new Uint8Array(totalChunksArray.buffer), offset);
          offset += 4;

          // Copy bodyChunk
          messageBuffer.set(new Uint8Array(bodyChunk), offset);

          // Send the message
          socket.send(messageBuffer.buffer);
          console.debug(
            `Sent body chunk ${i + 1}/${totalChunks} for ID: ${id}`,
          );
        }
      } else {
        console.debug(`No body to send for ID: ${id}`);
      }
    });
  }
}
