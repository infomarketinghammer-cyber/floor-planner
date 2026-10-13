import express, { Router } from 'express';
import rateLimit from 'express-rate-limit';
import jwt from 'jsonwebtoken';
import { config } from '../config.js';
import { authenticate } from '../middleware/auth.js';

export const authRouter = Router();
authRouter.use(express.json({ limit: '10kb' }));

function setSessionCookie(res, token) {
  const { exp } = jwt.decode(token);
  res.cookie(config.cookieName, token, {
    httpOnly: true,
    secure: config.isProduction,
    sameSite: 'strict',
    path: '/',
    expires: new Date(exp * 1000),
  });
}

async function callFastApi(path, init = {}) {
  const response = await fetch(`${config.fastapiUrl}/api/v1${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...init.headers },
  });
  const body = response.status === 204 ? null : await response.json();
  return { status: response.status, body };
}

/** Login and register: FastAPI issues the token, the gateway stores it in an httpOnly cookie. */
function issueSession(path) {
  return async (req, res, next) => {
    try {
      const { status, body } = await callFastApi(path, {
        method: 'POST',
        body: JSON.stringify(req.body ?? {}),
      });
      if (status >= 400) return res.status(status).json(body);
      setSessionCookie(res, body.access_token);
      return res.status(status).json({ user: body.user });
    } catch (err) {
      return next(err);
    }
  };
}

// Only credential attempts are rate-limited. The /me session check runs on every page load and
// must never be throttled, or signed-in users would appear logged out.
const credentialLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 30,
  standardHeaders: 'draft-8',
  legacyHeaders: false,
  message: { detail: 'Too many sign-in attempts. Try again in a few minutes.' },
});

authRouter.post('/login', credentialLimiter, issueSession('/auth/login'));
authRouter.post('/register', credentialLimiter, issueSession('/auth/register'));

authRouter.post('/logout', (req, res) => {
  res.clearCookie(config.cookieName, { path: '/' });
  res.status(204).end();
});

authRouter.get('/me', authenticate, async (req, res, next) => {
  try {
    const { status, body } = await callFastApi('/auth/me', {
      headers: { authorization: req.headers.authorization },
    });
    if (status === 401) res.clearCookie(config.cookieName, { path: '/' });
    return res.status(status).json(status >= 400 ? body : { user: body });
  } catch (err) {
    return next(err);
  }
});
