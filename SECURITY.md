# Security policy

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository. Do not open a
public issue containing an API key, credential, private response payload, exploit or
other sensitive information.

Include the affected version, impact, reproduction steps and a minimal sanitized
example. Remove TfNSW keys, Hermes configuration, home-directory paths and personal
travel details before submitting evidence.

## Credential handling

`TFNSW_API_KEY` is a deployment secret. The plugin reads it from the Hermes runtime
environment and sends it only as an authorization header to allowlisted TfNSW
origins. It must never be committed, logged, embedded in source, included in prompts
or attached to an issue.

If a key may have been exposed, revoke or rotate it in the TfNSW Open Data portal.
Deleting a secret from the latest Git revision is not sufficient because old Git
objects, forks, caches and logs may retain it.

## Supported version

Security fixes target the latest release and the current `main` branch. Older alpha
versions may require upgrading rather than a backport.
