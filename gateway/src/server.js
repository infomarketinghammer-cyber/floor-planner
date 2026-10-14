import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import cookieParser from 'cookie-parser';
import express from 'express';
import helmet from 'helmet';
import { createProxyMiddleware } from 'http-proxy-middleware';
import morgan from 'morgan';
import { config } from './config.js';
import { authenticate, requireRole } from './middleware/auth.js';
import { authRouter } from './routes/auth.js';

const app = express();
app.disable('x-powered-by');
app.set('trust proxy', config.trustProxy);

app.use(helmet());
app.use(morgan(config.isProduction ? 'combined' : 'dev'));
app.use(cookieParser());

app.get('/health', (req, res) => res.json({ status: 'ok' }));
// Ready when FastAPI answers too: for the host's health check, so traffic only arrives once
// both are up.
app.get('/ready', async (req, res) => {
  try {
    const response = await fetch(`${config.fastapiUrl}/health`, { signal: AbortSignal.timeout(3000) });
    return res.status(response.ok ? 200 : 503).json({ status: response.ok ? 'ok' : 'backend unavailable' });
  } catch {
    return res.status(503).json({ status: 'backend unavailable' });
  }
});

// --- Encrypt in transit (PRD 4.14): in production, plain HTTP is redirected to HTTPS. Behind a
// TLS-terminating proxy, `trust proxy` makes req.secure follow X-Forwarded-Proto. Helmet sends
// HSTS so browsers stay on HTTPS.
if (config.isProduction && config.forceHttps) {
  app.use((req, res, next) => {
    if (req.secure || req.path === '/health' || req.path === '/ready') return next();
    return res.redirect(308, `https://${req.headers.host}${req.originalUrl}`);
  });
}

// --- Public auth routes (handled by the gateway, which owns the session cookie)
app.use('/api/auth', authRouter);

// --- Role-guarded route groups
app.use('/api/admin', authenticate, requireRole('admin'));
app.use('/api/projects', authenticate, requireRole('contractor', 'admin'));

// Reject oversized uploads before streaming them to FastAPI (1 MB allowance for multipart overhead).
app.post(['/api/projects/:projectId/files', '/api/projects/:projectId/rooms/import'], (req, res, next) => {
  const length = Number(req.headers['content-length'] ?? 0);
  if (length > (config.maxUploadMb + 1) * 1_048_576) {
    return res.status(413).json({ detail: `The file is too large; the limit is ${config.maxUploadMb} MB.` });
  }
  return next();
});

// --- Public, no login: how this deployment handles data (privacy page)
app.use(
  '/api/public',
  createProxyMiddleware({
    target: config.fastapiUrl,
    pathRewrite: (reqPath) => `/api/v1/public${reqPath}`,
  }),
);

// --- Guest mode (no login): the browser sends its project with each call; nothing is stored.
// Projects with plan files are large, so the limit is higher than for uploads.
app.post('/api/guest/call', (req, res, next) => {
  const length = Number(req.headers['content-length'] ?? 0);
  if (length > config.maxGuestCallMb * 1_048_576) {
    return res.status(413).json({ detail: `This project is too large to work on without an account (over ${config.maxGuestCallMb} MB). Sign in to keep working.` });
  }
  return next();
});
app.use(
  '/api/guest',
  createProxyMiddleware({
    target: config.fastapiUrl,
    pathRewrite: (reqPath) => `/api/v1/guest${reqPath}`,
    // FastAPI rate-limits guests by client IP: send the one worked out from the trusted
    // proxies (replacing anything the client sent), not the spoofable X-Forwarded-For.
    on: { proxyReq: (proxyReq, req) => proxyReq.setHeader('x-client-ip', req.ip ?? '') },
  }),
);

// --- Everything under /api is authenticated and proxied to FastAPI as /api/v1/*
app.use(
  '/api',
  authenticate,
  createProxyMiddleware({
    target: config.fastapiUrl,
    pathRewrite: (reqPath) => `/api/v1${reqPath}`,
    on: {
      error: (err, req, res) => {
        console.error('FastAPI proxy error:', err.message);
        if (!res.headersSent) res.status(502).json({ detail: 'Backend unavailable' });
      },
    },
  }),
);

// --- Serve the built React app when it's there (single-server deployments). In development Vite
// serves it; when the frontend is hosted separately (e.g. Vercel) there is no build here.
const distDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../frontend/dist');
if (config.isProduction && existsSync(path.join(distDir, 'index.html'))) {
  app.use(express.static(distDir));
  app.get('/{*splat}', (req, res) => res.sendFile(path.join(distDir, 'index.html')));
}

app.use((err, req, res, next) => {
  console.error(err);
  res.status(500).json({ detail: 'Internal server error' });
});

app.listen(config.port, () => {
  console.log(`Gateway listening on http://localhost:${config.port} -> ${config.fastapiUrl}`);
});
