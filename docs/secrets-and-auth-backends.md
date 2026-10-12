# Secrets and authentication backend design

- **Status:** Exploration; prerequisite design, not implementation approval
- **Date:** 2026-10-12
- **Scope:** Portable application contracts and deployment-adapter responsibilities

## Decision to make

Mission Control needs a small, backend-neutral way to use sensitive material
before any public access design can be considered complete. The first contract
should stay close to a key-path/value store, but it must make expiry,
concurrency, revocation, and backend limitations explicit. Secret storage must
not be conflated with authentication, authorization, or web-session handling.

This note is a discussion specification. It does not choose Vault, add an
identity provider, change the runtime, migrate credentials, or authorize public
exposure. The existing rule remains: secret values are runtime inputs and must
not enter application configuration, SQLite, logs, Git, generated artifacts, or
the Nix store.

The [remote PWA access review](remote-access-design.md) treats this work as a
prerequisite because certificate keys, enrollment invitations, identity-provider
credentials, and session-signing material all need lifecycle controls.

## Keep four concerns separate

1. **Secret storage lifecycle** stores and retrieves opaque bytes and associated
   lifecycle metadata.
2. **Authentication** verifies a person or service and returns a validated
   principal assertion.
3. **Authorization** decides whether that principal may perform a named action
   on a resource.
4. **Session management** creates, validates, rotates, and revokes bounded web
   sessions after authentication.

A backend may implement more than one concern, but the public interfaces should
not assume that it does. In particular, an encrypted file store is not an
identity provider, and an identity provider is not necessarily the owner of TLS
private keys.

## Classify material before storing it

| Material | Expected handling |
| --- | --- |
| Public certificates, public keys, credential IDs, algorithms, and non-secret policy metadata | May live in ordinary configuration or application storage when disclosure is acceptable. Integrity still matters. |
| Server private keys, OAuth refresh tokens, invitation secrets, session-signing keys, and backend access tokens | Must use the secret lifecycle boundary and runtime-only delivery. |
| Session tokens and one-time codes | Store only a verifier or digest when the protocol allows it; enforce expiry on every use and support revocation. |
| Client or authenticator private keys | Must remain with the client authenticator. Mission Control stores only the public credential and metadata required for verification. |

Classification is part of each consumer's contract. A field does not become
safe merely because a backend encrypts it at rest.

## Proposed minimal secret contract

The proposed simple model is the right baseline:

```text
put(key_path, value, options) -> secret_ref
get(key_path, read_options) -> secret_value + metadata | not_found | expired
delete(key_path, delete_options) -> deleted | not_found
metadata(key_path) -> metadata | not_found
capabilities() -> backend_capabilities
```

The initial contract should require only `put`, `get`, `delete`, metadata, and
capability discovery. It should not require every backend to emulate Vault.
`value` is opaque bytes; callers, not the backend, own serialization.

Minimum metadata:

- normalized logical key path;
- opaque version or revision;
- creation and last-update timestamps;
- optional `expires_at`;
- non-secret content type or purpose;
- backend identifier and backend-specific opaque reference;
- state: active, expired, deleted, or revoked when supported.

Minimum options:

- create-only, replace, or compare-and-set against an expected version;
- optional `expires_at` supplied as an absolute timestamp;
- optional delete of one version or the logical key, when supported.

`get` must reject an expired value even if a cleanup job has not deleted the
bytes. This is the authorization property. Timer-driven deletion is hygiene and
space reclamation, not TTL enforcement.

### Optional capabilities

Capability discovery prevents the abstraction from promising a lowest-common-
denominator feature that a backend cannot safely provide. Optional capabilities
may include:

- atomic compare-and-set;
- version history and version-specific reads;
- recoverable deletion and irreversible destruction;
- native leases, renewal, and revocation;
- backend-enforced expiry or delayed deletion;
- key listing, which should be disabled unless a consumer truly needs it;
- audit-event correlation without exposing the value;
- generated or dynamic credentials.

A consumer declares required capabilities during preflight. Startup or feature
activation fails closed if the selected backend cannot satisfy them. There is no
plaintext SQLite fallback.

## Key-path and policy rules

Logical paths should use a canonical, language-neutral form such as:

```text
core/<purpose>/<name>
plugin/<plugin-id>/<connection-id>/<name>
deployment/<component>/<name>
```

The core validates each segment before a backend sees it: Unicode normalization
is fixed, empty segments and `.` or `..` are rejected, separators cannot be
escaped, length is bounded, and a plugin cannot select another plugin's or a
core namespace. A logical path is not a filesystem path or a Vault path; each
adapter performs a safe, injective mapping.

Policies grant narrowly scoped operations to a core service or one plugin
namespace. Plugins receive a namespaced secret service through their documented
context, not backend credentials, raw filesystem paths, or a global client.
In-process plugins remain trusted code, as described in `INTERFACES.md`; this
contract narrows accidental access but is not an operating-system sandbox.

Audit records may include operation, principal/service identity, logical
namespace, result class, backend, version, and correlation ID. They must redact
values, tokens, authorization headers, and sensitive path segments selected by
policy. Errors and health output follow the same rule.

## Authentication, authorization, and session contracts

These should be designed independently after the secret lifecycle contract is
proven:

- an **authenticator** accepts a protocol-specific request and returns a
  versioned principal assertion, authentication time, method, and assurance
  attributes;
- an **authorizer** evaluates principal, action, resource, and context and
  returns allow or deny with a stable reason code;
- a **session service** issues an opaque handle or signed token, validates idle
  and absolute expiry, rotates signing keys, and revokes one session, one
  credential, or all sessions for a principal.

No plugin may interpret raw identity-provider claims or weaken core
authorization. Plugins declare permissions in registration; core validates and
authorizes before dispatch. This follows the repository's existing public
plugin and CUE-validation direction without freezing a schema before there is a
working vertical slice.

Candidate contracts should first be written as closed, versioned CUE documents
with generated JSON Schema and conformance fixtures. Publish them only after a
reference consumer and two materially different secret backends prove that the
shapes are portable.

## Candidate backend A: local encrypted files on NixOS

A small deployment adapter could encrypt one file per logical key with
[`age`](https://github.com/FiloSottile/age), keep ciphertext in mutable host
state, and deliver decrypted values through
[`systemd` service credentials](https://systemd.io/CREDENTIALS/). `age` is a
file-encryption tool; its identity files contain secret keys. It does not supply
authentication, policy, leases, audit, or TTL semantics.

The root encryption identity is the real root secret. Encrypting files without
protecting that identity only moves the trust boundary. The design must decide
whether it is protected by host permissions, a hardware-backed mechanism, an
operator-held recovery key, or another secret service, and must test boot and
recovery behavior.

systemd credentials are acquired at service activation, restricted to the
service user, and can be delivered from encrypted credential files. They are a
good runtime-delivery mechanism, but credentials are immutable during a service
run; rotation therefore needs an explicit reload/restart or another bounded
delivery protocol.

A systemd timer can delete expired ciphertext and can be configured to catch up
after downtime. That cleanup is best effort. Reads and authentication checks
must still enforce `expires_at`, including across restart, timer failure, clock
correction, backup restore, and host downtime. Removing a directory entry is
not a promise of secure erase on flash storage, snapshots, journaled
filesystems, backups, logs, process memory, or caches.

Nix should package the adapter, service units, policy, and non-secret paths.
Secret values, private identities, or generated plaintext must never be Nix
expressions or derivation inputs. Nix store objects are immutable; runtime
credentials belong in mutable host state or a credential-delivery channel.

This candidate is operationally small and reproducible, but Mission Control
would own versioning, expiry checks, policy, audit, rotation orchestration, and
recovery semantics.

## Candidate backend B: Vault

[Vault KV v2](https://developer.hashicorp.com/vault/docs/secrets/kv/kv-v2)
stores and versions arbitrary static secrets. Its API exposes versions,
compare-and-set, metadata, soft deletion, destruction, maximum versions, and
`delete_version_after`. These map well to optional capabilities, but should not
leak into the portable baseline.

Vault's [lease model](https://developer.hashicorp.com/vault/docs/concepts/lease)
applies to dynamic secrets and service-type tokens. Vault explicitly notes that
the KV backend does not issue leases. Therefore, storing `expires_at` metadata
beside a KV value is not equivalent to a renewable, revocable lease, and native
auto-revocation must not be advertised for a plain KV adapter.

Vault adds mature policy, audit, authentication, dynamic-secret, and revocation
options, but also adds a separate highly privileged service, unseal and recovery
procedures, availability dependencies, upgrades, backups, and its own access
credentials. It is a candidate when those capabilities justify the operational
cost, not a mandatory dependency for a small installation.

## Failure and lifecycle semantics

- Backend unavailable, sealed, or unauthenticated: fail closed for any operation
  requiring the secret. Cached plaintext is not an indefinite fallback.
- Expired: return `expired`, never the value, even if physical cleanup is late.
- Concurrent update: compare-and-set conflict is explicit; do not silently
  overwrite a rotated value.
- Rotation: support overlap where the consuming protocol needs it, then revoke
  the old version and invalidate dependent sessions or credentials.
- Restart: define which material may be reacquired, which services must restart,
  and what happens to in-flight sessions.
- Backup and restore: document whether ciphertext, metadata, root keys, audit
  state, and revocation state are included. Test restore into an isolated host.
- Delete: distinguish logical deletion, recoverable deletion, irreversible
  backend destruction, protocol-level revocation, and physical media erasure.
- Caches: bound lifetime, zero or replace buffers where practical, never log,
  and invalidate on rotation, revoke, expiry, or backend policy change.

## Migration and staged validation

1. Inventory current credential flows and classify every field without moving
   data.
2. Draft an internal interface and CUE fixtures for key paths, metadata,
   capability negotiation, errors, and redaction.
3. Build an in-memory test backend only for contract tests; forbid it in
   production configuration.
4. Prototype one local runtime-credential adapter and one Vault adapter against
   the same conformance suite.
5. Exercise create-only writes, CAS rotation, expiry-on-read, delayed cleanup,
   deletion, revocation, backend outage, restart, backup restore, and corrupted
   ciphertext.
6. Migrate one low-blast-radius credential with a reversible cutover. Do not
   delete the old copy until the rollback window closes; ensure both copies are
   access-controlled and audited during overlap.
7. Only then draft authentication, authorization, and session schemas using a
   complete login-to-authorized-command vertical slice.
8. Require this work, recovery drills, and threat review before advancing any
   public remote-access proposal.

## Decisions still required

- Which operations and metadata belong in the mandatory v1 baseline?
- Is list required, or should discovery remain outside the secret interface?
- Which consumers require CAS, history, native leases, or generated secrets?
- What is the local backend's root-key and disaster-recovery model?
- Does local rotation restart consumers, use a socket provider, or wait for a
  later dynamic-delivery contract?
- What audit path remains available during backend outage, and how is its own
  integrity protected?
- Which identity provider, WebAuthn recovery policy, authorization model, and
  session representation will be evaluated after secret storage is proven?
- What migration and rollback window is acceptable for existing credentials?

## Primary sources

- Mission Control [`ARCHITECTURE.md`](../ARCHITECTURE.md) and
  [`INTERFACES.md`](../INTERFACES.md)
- [Vault KV v2 overview](https://developer.hashicorp.com/vault/docs/secrets/kv/kv-v2)
- [Vault KV v2 API](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2)
- [Vault leases, renewal, and revocation](https://developer.hashicorp.com/vault/docs/concepts/lease)
- [`age` project and usage documentation](https://github.com/FiloSottile/age)
- [systemd system and service credentials](https://systemd.io/CREDENTIALS/)
- [systemd timer units](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html)
- [Nix store object immutability](https://nix.dev/manual/nix/stable/store/store-object)
