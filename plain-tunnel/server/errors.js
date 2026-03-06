function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function errorResponse(status, title, message, accept) {
  const safeTitle = escapeHtml(title);
  const safeMessage = escapeHtml(message);

  if (accept && accept.includes("text/html")) {
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${status} · Plain Tunnel</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background: #f7f7f4;
      color: #3a352f;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .container {
      text-align: center;
      padding: 2rem;
      max-width: 28rem;
    }
    .status {
      font-size: 4rem;
      font-weight: 300;
      letter-spacing: -0.02em;
      color: #a8a29e;
      line-height: 1;
    }
    .title {
      margin-top: 1rem;
      font-size: 1.25rem;
      font-weight: 500;
    }
    .message {
      margin-top: 0.75rem;
      font-size: 0.875rem;
      font-weight: 300;
      color: #78716c;
      line-height: 1.5;
    }
    .brand {
      margin-top: 2.5rem;
      font-size: 0.75rem;
      font-weight: 400;
      color: #a8a29e;
      letter-spacing: 0.05em;
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="status">${status}</div>
    <h1 class="title">${safeTitle}</h1>
    <p class="message">${safeMessage}</p>
    <div class="brand">Plain Tunnel</div>
  </div>
</body>
</html>`;
    return new Response(html, {
      status,
      headers: { "Content-Type": "text/html; charset=utf-8" },
    });
  }

  return new Response(`${title}: ${message}`, {
    status,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
