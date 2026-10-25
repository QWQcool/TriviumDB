#!/usr/bin/env node
// Local preview of the V4 design draft. No database or product server required.
// Run: bun scripts/v4-preview.mjs (Node.js also works).
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';

const port = Number(process.env.V4_PREVIEW_PORT || 8894);
if (!Number.isInteger(port) || port < 1 || port > 65535) {
  throw new Error('V4_PREVIEW_PORT must be an integer from 1 to 65535');
}
const draft = new URL('../docs/design/webui-html-drafts/v4-workspace-unification.html', import.meta.url);
const server = createServer(async (request, response) => {
  if (!['GET', 'HEAD'].includes(request.method)) {
    response.writeHead(405, { Allow: 'GET, HEAD' });
    response.end();
    return;
  }
  const pathname = new URL(request.url, 'http://127.0.0.1').pathname;
  if (pathname === '/favicon.ico') {
    response.writeHead(204);
    response.end();
    return;
  }
  if (!['/', '/v4', '/v4/'].includes(pathname)) {
    response.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Not found');
    return;
  }
  try {
    const html = await readFile(draft);
    response.writeHead(200, {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Content-Type-Options': 'nosniff',
    });
    response.end(request.method === 'HEAD' ? undefined : html);
  } catch (error) {
    console.error('[v4-preview]', error.message);
    response.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('Unable to read the V4 draft');
  }
});
server.on('error', error => { console.error('[v4-preview]', error.message); process.exitCode = 1; });
server.listen(port, '127.0.0.1', () => {
  console.log(`V4 design preview: http://127.0.0.1:${port}/v4`);
});
