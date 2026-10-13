const required = ['JWT_SECRET'];
for (const key of required) {
  if (!process.env[key]) throw new Error(`Missing required env var ${key}`);
}

export const config = {
  port: Number(process.env.PORT ?? 4000),
  fastapiUrl: process.env.FASTAPI_URL ?? 'http://127.0.0.1:8000',
  jwtSecret: process.env.JWT_SECRET,
  isProduction: process.env.NODE_ENV === 'production',
  cookieName: 'fp_session',
  // Keep in sync with backend MAX_UPLOAD_MB; FastAPI enforces the exact limit.
  maxUploadMb: Number(process.env.MAX_UPLOAD_MB ?? 25),
};
