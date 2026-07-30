# Security Policy

## Reporting a vulnerability

Please do **not** open a public issue for security vulnerabilities.
Instead, email **uic.mubin@gmail.com** with:

- A description of the vulnerability and its impact
- Steps to reproduce
- Any suggested mitigation

You will receive a response within a reasonable timeframe, and a fix will be
prioritized based on severity.

## Deployment guidance

- The Docker image defaults to `ENVIRONMENT=development`, which allows
  unauthenticated access so the Studio works out of the box. **Before exposing
  an instance beyond localhost, set `ENVIRONMENT=production`** and configure
  local users/API keys or Keycloak.
- Set a strong `SECRET_KEY` (JWT signing) and `DELAXIS_ADMIN_PASSWORD`.
- Never commit `.env` files; use the provided `.env.example` as a template.
- Deployed chat pages (`/d/<name>/`) are public by design — do not deploy
  workflows that expose sensitive tools without authentication in front.
