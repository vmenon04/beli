# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Report it privately through GitHub: on the repository's **Security** tab, choose **Report a vulnerability**.

Include the version (`pip show beli`), what you found and how to reproduce it. Never include a real token, password or session file.

Only the latest release is supported with security fixes.

## What counts

Reports are especially welcome for anything that could:

- expose a token, password or session file (in logs, error messages, files written with loose permissions, or requests sent to the wrong host);
- make the package send a request that changes an account. It is meant to be read-only.

A change on Beli's side that breaks an endpoint is a bug, not a vulnerability: open a normal issue.
