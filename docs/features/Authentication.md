# Feature PRD: User Authentication & RBAC

## 1. Purpose
To provide secure, stateless identity verification and strict Role-Based Access Control (RBAC) across the NANFO platform[cite: 1]. This ensures that only authorized administrators and specialized engineers can execute high-impact network configurations.

## 2. Requirements
* Implement stateless authentication utilizing JSON Web Tokens (JWT)[cite: 1].
* Support token lifecycle management (issue, refresh, revoke/logout).
* Enforce fine-grained RBAC for different user personas (e.g., Enterprise NOC Engineers, SDN & Wireless Engineers, Tertiary Users)[cite: 1].
* All authentication events must append records to the immutable Audit Log[cite: 1].

## 3. API Endpoints
All endpoints must adhere to the standard REST envelope defined in `docs/api/API_STANDARD.md`.
* `POST /api/v1/auth/login` - Authenticate user and issue JWT[cite: 1].
* `POST /api/v1/auth/logout` - Invalidate current session/token[cite: 1].
* `POST /api/v1/auth/refresh` - Issue a new JWT using a valid refresh token[cite: 1].
* `GET /api/v1/auth/me` - Retrieve current user profile and active permissions[cite: 1].

## 4. Database Schema Requirements
This feature strictly owns the following tables within the PostgreSQL relational store[cite: 1]:
* `users`: Stores UUID, email, hashed password, and status.
* `roles`: Defines system roles (e.g., Admin, Read-Only, Operator).
* `permissions`: Defines granular capabilities (e.g., `execute:rollback`, `write:config`).
* `user_roles`: Mapping table for user-to-role relationships[cite: 1].
* `audit_logs`: Immutable, append-only table for recording login successes, failures, and token issuances[cite: 1].

## 5. Security & Validation (Edge Cases)
* **Passwords:** Must never be logged or returned in any API response.
* **Brute Force:** Implement rate limiting on the `/login` endpoint (e.g., max 5 failed attempts per IP before temporary lockout).
* **Validation:** Reject malformed email formats or weak passwords with a `422 Unprocessable Entity` before hitting the Service Layer.
* **Token Expiration:** Access tokens should have a short lifespan (e.g., 15 minutes); refresh tokens should handle long-lived sessions.

## 6. Acceptance Criteria
- [ ] Submitting valid credentials to `/login` returns a 200 OK with a valid JWT and standard meta envelope.
- [ ] Submitting invalid credentials returns a `401 Unauthorized` without specifying whether the email or password was wrong.
- [ ] Accessing a protected route without a JWT returns a `401 Unauthorized`.
- [ ] Accessing a protected route with insufficient RBAC permissions returns a `403 Forbidden`.
- [ ] Successful and failed authentication attempts are successfully written to the `audit_logs` table.

## 7. Testing Requirements
* Refer to `.agents/rules/testing.md` for standards.
* Write isolated unit tests for the JWT encoding/decoding utility functions.
* Write integration tests for the FastAPI router endpoints using an injected test database.