# Security Policy

## Supported versions

ctxvc is pre-1.0; security fixes are applied to the latest release only.

## Reporting a vulnerability

Please **do not open a public issue** for security vulnerabilities.

Instead, report privately via GitHub's
[private vulnerability reporting](https://github.com/namrathshetty/ctxvc/security/advisories/new)
(Security tab → "Report a vulnerability"), or email the maintainer.

Include:
- a description of the issue and its impact,
- steps to reproduce or a proof of concept,
- the affected version / commit.

You can expect an initial acknowledgement within a few days. Once a fix is
available, we will coordinate disclosure.

## Handling of secrets

ctxvc never stores cloud credentials in the repository config. S3 credentials
come from the standard AWS credential chain (environment, shared config, IAM
role, or a named profile), and the Qdrant API key is read from an environment
variable named in the index config. Please keep it that way in contributions.
