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
app.set('trust proxy', 1);

app.use(helmet());
app.use(morgan(config.isProduction ? 'combined' : 'dev'));
app.use(cookieParser());

app.get('/health', (req, res) => res.json({ status: 'ok' }));

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

// --- Serve the built React app in production (Vite serves it in development)
if (config.isProduction) {
  const distDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../frontend/dist');
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
