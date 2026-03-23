export function landingPage(title, message) {
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${title}</title>
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
    .container { text-align: center; padding: 2rem; max-width: 28rem; }
    .title { font-size: 1.25rem; font-weight: 500; }
    .message { margin-top: 0.75rem; font-size: 0.875rem; font-weight: 300; color: #78716c; line-height: 1.5; }
  </style>
</head>
<body>
  <div class="container">
    <h1 class="title">${title}</h1>
    <p class="message">${message}</p>
  </div>
</body>
</html>`;
  return new Response(html, {
    status: 200,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}
