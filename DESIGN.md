# AI Support Operations · White workspace

## Direction
Operate surface for Vietnamese support agents and managers. User requested white, modern and readable across all screens. White canvas, pale navigation rail, deep blue actions, dark ink and fine cool borders. No decorative imagery or marketing layouts.

## System
- DM Sans body and Manrope headings; Lucide icons.
- Body 14px, metadata 12px, page heading 30px. Tabular numerals for measured data.
- White #ffffff, rail #f8fafc, ink #172b4d, secondary #475569, border #e2e8f0, action #1d4ed8.
- Semantic red for errors, amber for human handoff, green for approved/completed.
- Consistent 8px controls and 12px panels, restrained shadows, visible keyboard focus.
- Design variance 3, motion intensity 2, visual density 6: an operational workspace with long reading sessions.

## Behavior
- AI drafts require human review. Missing evidence and sensitive requests show handoff.
- Provider errors persist beside the AI action, with retry. Never invent an answer when Gemini fails.
- Ticket assignment and status remain available on tablet/mobile, below the conversation when needed.
- Navigation icons retain accessible names when collapsed; workspace switching and logout remain available.
- White color scheme is explicit in CSS and document metadata.
- All permissions, data boundaries, pages and workflows remain enforced by the backend.


## Self-service account surfaces
- The account flow inherits the white and blue product identity. Desktop uses a pale context column and a clear form column; mobile keeps branding and form in one column.
- Business registration starts an empty workspace, a default support team and an owner membership. No hardcoded company name appears in the product shell.
- Teams and ticket creation use inline forms. Invitation links show their expiry, can be copied, and can be revoked; SMTP acceptance or failure is shown beside the copyable link and retained in the invitation list. Never claim inbox delivery from SMTP acceptance.
- Workspace switching only lists memberships belonging to the signed-in account. Profile controls never impersonate another user.

## Subscription controls
- Billing extends Settings with plan status, exact expiration date, inline bank checkout, and order history. Keep the white workspace, blue action, and semantic green/amber status palette.
- Trial/expired status remains visible in the shell. QR confirmation is server-authoritative; pending, paid, expired, missing configuration and loading failures have explicit text.
- Stack QR/details and history rows on mobile; transfer codes wrap and have accessible copy controls.

## Brand mark
- Support Ops uses an authored cobalt (#1d4ed8) mark with two white dialogue strokes forming an S.
- Shared asset: public/assets/brand/support-ops-mark.svg; used by sidebar, account screens and browser favicon.
- Keep the mark square and unanimated, without shadows or recoloring. The adjacent wordmark supplies the accessible name.
