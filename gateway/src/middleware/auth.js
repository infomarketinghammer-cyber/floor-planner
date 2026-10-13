import jwt from 'jsonwebtoken';
import { config } from '../config.js';

/**
 * Reads the session cookie, verifies the JWT and forwards it to FastAPI as a Bearer token.
 * FastAPI re-verifies the token and the user's current status on every request.
 */
export function authenticate(req, res, next) {
  if (req.user) return next();

  const token = req.cookies?.[config.cookieName];
  if (!token) return res.status(401).json({ detail: 'Not authenticated' });

  try {
    const payload = jwt.verify(token, config.jwtSecret, { algorithms: ['HS256'] });
    req.user = { id: payload.sub, role: payload.role };
    req.headers.authorization = `Bearer ${token}`;
    return next();
  } catch {
    return res.status(401).json({ detail: 'Session expired' });
  }
}

export function requireRole(...roles) {
  return (req, res, next) => {
    if (!req.user || !roles.includes(req.user.role)) {
      return res.status(403).json({ detail: 'Insufficient permissions' });
    }
    return next();
  };
}
