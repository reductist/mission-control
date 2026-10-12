# Remote PWA access design

- **Status:** Exploration; no implementation decision
- **Date:** 2026-10-12
- **Scope:** Deployment-owner infrastructure outside the portable application

## Outcome to preserve

Authorized household users should be able to open the installed Android PWA at
home or away without routinely toggling a VPN. Mission Control itself should
remain isolated, and a compromised public gateway should have as little access
as possible to the home LAN, tailnet, and application backend.

This note records viable designs and verification gates. It does not approve
public exposure, add application authentication, or supersede the accepted
[network exposure decision](network-exposure.md). The current server has no user
authentication and must not be exposed directly to an untrusted network.

## Current constraints

- Mission Control normally listens on `127.0.0.1:8000`.
- The Android PWA is online-only. It has no offline shell or background worker
  that could bootstrap a closed network path.
- The documented private deployment option uses Tailscale Serve for trusted
  HTTPS access.
- Any direct LAN access to port 8000 would bypass a future gateway and must be
  removed before relying on gateway authentication.
- A normal browser PWA cannot send an arbitrary UDP single-packet authorization
  message. The Direct Sockets proposal is restricted to isolated application
  contexts, not ordinary installed PWAs.

## Design principles

1. Keep Mission Control loopback-bound and authenticate every application route
   before forwarding to it.
2. Enroll named people and credentials; do not treat a public source IP as a
   user or device identity.
3. Generate device private keys in the client authenticator and register only
   public credentials.
4. Keep routine public sessions short-lived and independently revocable.
5. Use outbound home connectivity or one narrowly scoped public gateway, not a
   broad LAN exposure.
6. Keep TLS, DNS, tunnel, invitation, and session secrets out of Git and the Nix
   store. Supply them as runtime credentials.
7. Preserve one stable HTTPS origin for the PWA. Split DNS may change the route,
   but not the hostname or origin.

## Recommended proposal for evaluation

The best current balance is a small public TCP relay with TLS termination and
authentication at home:

```text
Android PWA
  -> public VPS TCP/443 pass-through
  -> narrowly granted Tailscale path
  -> application-host Caddy TCP/443
  -> WebAuthn authentication gateway
  -> Mission Control 127.0.0.1:8000
```

The VPS can use HAProxy or Nginx stream mode to forward opaque TCP/TLS to a
dedicated Caddy listener on the home application host. The relay does not
receive the TLS private key. Caddy obtains the public certificate with DNS-01
and terminates TLS at home. A Tailscale grant permits the relay tag to reach
only that TCP/443 listener, not port 8000, SSH, or other tailnet nodes.

This proposal has no inbound home port and no routine phone VPN. It requires a
public VPS, its patching and availability, and a continuously available
Tailscale path between the relay and home.

### Trusted enrollment and public sessions

Use a mature authentication gateway rather than a custom key protocol.
[authentik](https://docs.goauthentik.io/add-secure-apps/flows-stages/stages/authenticator_webauthn/)
is the leading candidate because it already provides invitation flows,
WebAuthn/passkey enrollment and validation, user-verification controls, and a
[proxy/forward-auth provider](https://docs.goauthentik.io/add-secure-apps/providers/proxy/).
[Authelia](https://www.authelia.com/configuration/second-factor/webauthn/)
is a lighter alternative with WebAuthn and
[Caddy integration](https://www.authelia.com/integration/proxies/caddy/), but its
tailnet-trusted invitation ceremony needs more deployment policy.

A proposed ceremony is:

1. An administrator creates separate user accounts over a tailnet-only
   administration path.
2. The administrator mints a short-lived, single-use enrollment invitation.
3. The invitee redeems it at the stable public authentication origin.
4. The platform authenticator creates the private key and registers its WebAuthn
   public credential.
5. Later public assertions establish `Secure`, `HttpOnly`, `SameSite` sessions
   with idle and absolute expiration.
6. A lost credential and its sessions can be revoked without affecting the
   other person or device.

The invitation endpoint may be public, but enrollment must be impossible
without a tailnet-minted invitation. This is configuration of standard flows,
not custom authentication code.

The credential and session lifetimes are separate. WebAuthn credentials are
normally durable and explicitly revoked; the resulting web sessions carry the
bounded TTL. The deployment must choose whether to allow synced, backup-eligible
passkeys for easier recovery or require separately enrolled, device-bound
credentials. A strict-device policy needs a documented lost-device recovery
method.

## Why this resembles proven home-access systems

Home Assistant Cloud uses an outbound connection from the home instance to a
public UI proxy. The proxy routes using TLS SNI and a TCP multiplexer, while the
certificate private key and TLS termination remain on the Home Assistant
system. Its public login remains the authorization boundary. The implementation
family is published as [`snitun`](https://github.com/NabuCasa/snitun).

Apple Home uses device-generated Ed25519 identities and a trusted pairing
ceremony. Away-from-home commands are authenticated and end-to-end encrypted
through Apple Identity Service to an always-on home hub. The reusable pattern is
trusted enrollment plus an always-available relay and home-side enforcement.
HomeKit itself is not reusable: it depends on native Apple clients, platform key
storage, Apple identity infrastructure, and the HomeKit Accessory Protocol.

These systems do not teach a browser to traverse NAT. They provide a stable
relay and durable identity, then keep authorization at a trusted endpoint.

Primary sources:

- [Home Assistant remote access](https://www.home-assistant.io/docs/configuration/remote/)
- [Nabu Casa remote-access internals](https://support.nabucasa.com/hc/en-us/articles/25619268678557-Remote-access-Deep-dive)
- [Nabu Casa security model](https://support.nabucasa.com/hc/en-us/articles/26508882007581-Remote-access-Security-aspects)
- [Apple HomeKit communication security](https://support.apple.com/guide/security/communication-security-sec3a881ccb1/web)
- [Apple home hubs](https://support.apple.com/en-us/102557)
- [WebAuthn](https://www.w3.org/TR/webauthn-3/)

## Relay trust and certificate issuance

A correctly configured TCP relay sees addresses, timing, traffic volume, and
normally the TLS server name. It can drop, delay, or redirect connections, but
it cannot ordinarily read HTTP paths, cookies, WebAuthn assertions, WebSocket
payloads, or Mission Control data without the origin TLS private key.

There is an important certificate caveat. Because public DNS points at the VPS,
a compromised relay could answer HTTP-01 or TLS-ALPN-01 and try to obtain its
own certificate. Use DNS-01 only and publish CAA restrictions for the selected
CA, ACME account, and `dns-01` validation method. Keep authoritative DNS and the
registrar separate from the VPS provider, protect them with strong MFA, use a
narrow DNS API credential, enable DNSSEC where supported, and monitor
Certificate Transparency. CAA reduces risk but does not eliminate CA, DNS, or
global interception failures.

Sources:

- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [Let's Encrypt challenge types](https://letsencrypt.org/docs/challenge-types/)
- [Let's Encrypt CAA guidance](https://letsencrypt.org/docs/caa/)
- [CAA account and validation-method binding](https://www.rfc-editor.org/rfc/rfc8657)

## Alternatives

### Existing Tailscale baseline

First test the smallest existing solution: leave Tailscale connected and use
Android's always-on VPN facility if the installed Tailscale build exposes it.
Measure battery use, reboot recovery, and Wi-Fi/cellular handoff instead of
assuming a problem. This retains the current trusted network boundary and adds
no public service.

### Home-LAN-only HTTPS

Run Caddy on the application host, proxy to loopback port 8000, obtain a
certificate with DNS-01, and use local split DNS at home. Close raw LAN port
8000. This is the simplest design if away-from-home access is optional; remote
access still requires Tailscale.

### Managed outbound HTTPS tunnel

Cloudflare Tunnel plus Access is a mature no-inbound-port option with per-user
policy. It is operationally simpler than running a VPS. Cloudflare normally
presents the browser-facing certificate and opens a second encrypted leg to the
origin, so it can technically process HTTP plaintext and becomes an availability
and control dependency. This differs from TCP/TLS pass-through, where the relay
does not hold the origin key.

Sources:

- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/)
- [Tunnel firewall model](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall/)
- [Access for a self-hosted application](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/)
- [Cloudflare Full (strict) TLS](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/)

### On-premises isolated gateway on public TCP/443

An ingress host on a genuine VLAN-isolated DMZ can be a sound gateway. Forward
only TCP/443, use DNS-01, authenticate every route, and proxy over a narrow
Tailscale grant to port 8000. This keeps TLS on premises but requires a public
IPv4 address or equivalent IPv6 design, dynamic-DNS handling, router security,
and continuous gateway maintenance.

The router model is a prerequisite, not a detail. Support for SDN/VLAN networks,
physical-port access-mode binding, and inter-zone rules often varies between
closely named hardware revisions and firmware trains. The deployment must not
infer capability from a product family name. Verify the chassis model, region,
installed firmware, and actual wired-SDN controls in the router UI against the
vendor's current documentation.

The router's intranet-access control must also be tested for directionality. The desired
policy is home client to DMZ TCP/443 allowed while DMZ to home remains denied.
Do not enable broad intranet access if the router cannot express that rule.

Before selecting this path, prove public IPv4 rather than CGNAT. IPv6 requires
equivalent firewall and authentication policy; do not publish an AAAA record
until that path is tested. A raw UDP knock requires its own UDP forwarding rule.

### Single-packet authorization and silent filtering

Silently dropping TCP/443 before the host stack is a useful optional property,
not a substitute for authentication. It remains an unresolved requirement.

An XDP program can drop traffic early, but every software-XDP packet still uses
CPU, native mode depends on the exact gateway NIC and driver, and hardware offload has
not been established. Upstream fwknop documents traditional firewall backends,
not a released XDP backend.

A normal PWA cannot send the UDP authorization packet. If silent filtering is
mandatory, accept a native Android helper, keep its key in Android Keystore,
prefer mature fwknop/firewall behavior, and still require application
authentication. Source-IP allowlisting is fragile across mobile handoff and
over-grants unrelated clients behind shared carrier or hotel NAT.

Sources:

- [Direct Sockets proposal](https://wicg.github.io/direct-sockets/)
- [fwknop](https://github.com/mrash/fwknop)
- [fwknop XDP request](https://github.com/mrash/fwknop/issues/372)
- [XDP overview](https://iovisor.org/technology/xdp)

WebRTC, STUN, TURN, and WebSockets do not simplify this application. They still
need a reachable bootstrap/signaling endpoint; TURN is an external relay; and a
DataChannel would require a custom adapter for the existing HTTP application.

## Backend and proxy boundary

Before any public trial:

- authenticate every application and WebSocket route;
- reject unknown hosts and validate Origin/Referer on state-changing requests;
- strip client-supplied identity headers and add only gateway-generated values;
- configure trusted proxy ranges narrowly;
- retain Mission Control's same-origin write token;
- use secure session-cookie flags and both idle and absolute expiration;
- rate-limit login and enrollment;
- keep logs free of secrets and sensitive request bodies; and
- remove direct LAN and broad tailnet access to port 8000.

Caddy overwrites the standard `X-Forwarded-*` values by default, but any custom
identity headers also need explicit removal. The backend must not accept an
identity assertion through a path that bypasses the authenticating proxy.

A gateway or relay compromise is still material. VLAN isolation and Tailscale grants
limit lateral movement, but a gateway allowed to reach an unauthenticated
Mission Control backend can exercise that entire application capability.

## Least-privilege tailnet policy

Use current Tailscale `grants`, not legacy ACL syntax. An illustrative relay
policy would allow a generic relay tag to reach only a generic origin tag on a
dedicated TCP/443 listener. The on-premises alternative needs an equally narrow
path to the application port. These are design requirements, not copy-paste
policy: deployment-specific tag names, restrictive `tagOwners`, removal of
broader defaults, and automated positive and negative policy tests are required.

Sources:

- [Tailscale grants](https://tailscale.com/docs/features/access-control/grants)
- [Grant examples](https://tailscale.com/docs/reference/examples/grants)
- [ACL and grants guidance](https://tailscale.com/docs/features/access-control/acls)

## NixOS packaging boundaries

Keep deployment modules small and separable:

- the existing Mission Control module remains loopback-bound;
- a home ingress module owns Caddy, auth, host firewall, and runtime secrets;
- an optional relay module owns only TCP pass-through, Tailscale, and firewall;
- a managed-tunnel module exists only if that alternative is selected; and
- policy tests cover allowed and denied tailnet paths.

Pin packages and plugins through the flake lock. Store secret references in Nix,
but provide secret values through systemd credentials, agenix, or sops-nix so
they do not enter evaluation output, the Nix store, or Git.

## Verification gates

1. **Baseline:** measure Tailscale always-on behavior on one Android device for
   seven days, including reboot and Wi-Fi/cellular handoff.
2. **Inventory:** establish the exact router model/firmware, public IPv4 versus
   CGNAT, IPv6 posture, DNS records, and Android Private/Secure DNS behavior.
3. **Isolation:** on a disposable host, prove DMZ-to-home deny and the intended
   home-to-DMZ TCP/443 path. Re-test after router reboot.
4. **Authentication:** in a VM, test separate invitations and credentials,
   synced versus device-bound behavior, session expiry, revoke, recovery,
   CSRF/origin enforcement, header spoofing, and WebSocket upgrades.
5. **Policy:** prove the relay reaches only home TCP/443. Prove backend port
   8000, SSH, other ports, and other nodes are denied.
6. **Certificate:** issue and renew with port 80 closed. Validate DNS-01, CAA
   account/method restriction, DNSSEC behavior, and CT monitoring.
7. **Relay canary:** use a disposable hostname/backend. Prove the VPS has no TLS
   private key and packet capture contains only TLS ciphertext.
8. **External canary:** test each authorized Android device across home Wi-Fi,
   cellular, handoff, reboot, credential revoke, tunnel outage, and origin
   outage. All failures must fail closed.

## Decisions still required

- Is away-from-home access required?
- Does measured always-on Tailscale behavior already meet the goal?
- Is a small public VPS acceptable?
- Must TLS plaintext remain home-side, or is managed edge termination acceptable?
- Is silently filtered public TCP/443 a requirement or defense-in-depth wish?
- Are synced passkeys acceptable, or must credentials be bound to each device?
- What are the session idle and absolute TTLs?
- What is the lost-phone recovery and emergency revoke procedure?
- Which party owns VPS, DNS, certificate, auth, and dependency maintenance?

Implementation should start only after these decisions and verification gates
are reviewed separately.
