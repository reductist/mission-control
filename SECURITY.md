# Security policy

Mission Control is under active development and does not yet have a supported
stable release.

Do not open a public issue for a suspected vulnerability or accidentally
published secret. Use GitHub's private vulnerability reporting / Security
Advisory flow for this repository.

Never commit:

- passwords, API tokens, live webhook URLs, or private keys
- decrypted secret files
- authentication cookies or session data
- production database copies containing private household or infrastructure data
- private network inventories unless they are deliberately anonymized fixtures

Public examples and tests must use synthetic names, addresses, credentials,
identifiers, and network details.
