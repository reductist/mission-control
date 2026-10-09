# Install Mission Control on Android

Mission Control can be installed from Chrome as an online-only Progressive Web
App. It launches in its own window and uses the same private HTTPS origin as the
browser client. It does not include a service worker, offline cache, background
sync, or queued mutations: the app requires a live connection to Mission Control
for every read and write.

## Pixel installation

1. Connect the phone to the same tailnet as the Mission Control host.
2. In Chrome, open the private Mission Control HTTPS URL.
3. Wait for the overview to finish loading, then open Chrome's menu.
4. Choose **Install app**. If Chrome instead shows **Add to Home screen**, use
   that option and note which wording appeared when reporting the test result.
5. Launch **Mission Control** from the new home-screen or app-drawer icon.

## Pixel 7a acceptance checklist

- The installed icon is crisp and remains centered when Android applies its
  circular or themed-icon mask.
- Launching the icon opens a standalone Mission Control window without Chrome's
  address bar.
- The Overview is the initial screen and the mobile queue remains readable in
  portrait orientation without horizontal scrolling.
- Schedule, House, Maintenance, Yard, and History remain reachable and retain
  their current data and actions.
- Completing or adding a task succeeds while online and remains correct after
  reopening the app.
- Disconnecting Tailscale or otherwise going offline produces a normal network
  failure; it must not show stale private data or claim a write was queued.
- Reconnecting and relaunching loads current data again.

Chrome and Android decide whether installation produces a WebAPK or a simpler
home-screen shortcut. Confirming that result, icon masking, and standalone launch
behavior requires a real Android device; desktop browser checks cannot prove it.

## Security boundary

Installation does not publish Mission Control or change its listener, firewall,
authentication, or Tailscale configuration. The HTML document still carries the
same-origin write token and every response remains `Cache-Control: no-store`.
Keep using the access-controlled private HTTPS origin described in
[`network-exposure.md`](network-exposure.md); do not expose this unauthenticated
application through Tailscale Funnel or the public internet.
