# Decision 0001: Separate application consent for Google sources

## Status

Accepted — 2026-09-16

## Decision

Gmail and Google Drive use separate OAuth flows, encrypted credentials,
consent records, fetch policies, scheduled-access toggles, and purge actions.
Gmail requests `gmail.readonly`; Drive requests `drive.readonly`. Both add only
OpenID email identity so the application can bind and display the granting
Google account.

Drive discovery is restricted by application policy to one user-selected
folder and bounded recursive traversal. Gmail is restricted to selected labels.
Both sources default to a 24-hour lookback, small result limits, and scheduled
access off. Their extracted text is cleared after drafting and their drafts are
always routed to review in this release.

## Consequences

Google classifies both content scopes as restricted, so public production use
may require OAuth verification and a security assessment. The OAuth provider's
revocation endpoint removes all project grants for the affected Google account.
To preserve independent in-product controls, disconnecting one source deletes
its local token and data immediately but calls Google's revocation endpoint only
when no other active Google source uses that same account. The UI also exposes
Google's account-connections revocation path.
