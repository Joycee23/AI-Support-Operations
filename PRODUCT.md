# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

- Frontend: React + TypeScript + Vite.
- Backend: Python + FastAPI.
- Storage and vector search: PostgreSQL + pgvector.
- AI generation and embeddings: Gemini API called from backend adapters.

## Users and jobs

- Workspace administrators manage teams, membership, roles, and approved knowledge.
- Team managers operate tickets and membership within their teams.
- Support agents triage and resolve tickets within their permitted scope, with human review of every AI suggestion.

## Product purpose

Help multi-team support organizations process customer tickets. AI classifies and prioritizes tickets, retrieves accessible approved knowledge, and drafts Vietnamese replies with citations. People make every operational and sending decision. AI must abstain and route to a person when evidence is insufficient or the case is sensitive.

## Durable constraints

- This is a self-service SaaS for multiple businesses, with one calendar month free trial, then 499,000 VND per workspace per month. Each account can own or join multiple isolated workspaces. Never seed fictional customer data into newly registered workspaces.
- Gemini API is required for all AI features. The backend requires `GEMINI_API_KEY` at startup; never expose or log it. AI failures must be visible and must not produce mock success.
- Tenant and role authorization must be enforced by backend queries and mutations. Retrieval uses only approved knowledge accessible to the current user.
- Replies are never sent automatically. Agent confirmation saves a reply to ticket history; external sending is not connected.
- Email/password accounts use server-side sessions. Invitations send via configured TLS SMTP and retain a copyable link; delivery failures never invalidate the invitation. SSO, verification/recovery, external ticketing and retention need their own later integrations.
- No personal data from real people, unmeasured performance claims, or sensitive ticket content in logs.

## Open decisions

- [User confirmed] One-month free trial, 499,000 VND/workspace/month, SePay VietQR with authenticated webhook confirmation, private workspaces and member invitations. Existing fictional records are retained but never exposed through a demo identity header.
- [Open] Account recovery/verification, external ticketing, retention, usage quotas and deployment host.

## Billing constraints

- Persist workspace trials and paid access; expiration retains read access and blocks business mutations/AI.
- Payments use immutable orders, exact amount/account/code matching, unique provider transaction receipts and row locks. Never activate subscriptions from browser claims.
- Credentials and public HTTPS webhook configuration are deployment requirements. Reconciliation/refunds and usage quotas are not automated.
