# Parent-operated family rewards

The Family rewards plugin records small, independently earned amounts of play
credit while keeping the rules visible and predictable for adults. It is a
ledger and parent workflow, not a behavior score, countdown timer, child login,
or device-control system.

Enable it in the application configuration:

```toml
[plugins.family-rewards]
enabled = true
```

The validated defaults are deliberately generic:

- four morning tasks, each worth 10 minutes;
- a 40-minute school-day play cap and a 60-minute non-school-day cap;
- an afternoon weekday window and a daytime weekend window;
- `America/New_York` as the family-date timezone.

Every value can be changed in the parent Rewards view. The four tasks remain
independent: getting dressed before going downstairs, participating in
breakfast (never the quantity eaten), brushing teeth, and filling a water
bottle plus packing snacks/backpack. Reminders and parent support count. There
is no fifth learning activity, streak, deadline cliff, expiry, or debt.

## Ledger behavior

An award stores the minute value in force at the time it is earned. Later
configuration changes do not rewrite history. Redemptions are limited by the
available balance, the effective cap for that local date, and the existence of
an eligible recurring or overridden play window. Credit carries over without
expiry.

Ledger rows are immutable. An erroneous award creates an explicit reversal;
an abandoned redemption creates an explicit refund. A correction that would
make the balance negative is rejected. The audit history records the actor,
family date, amount, note, and the entry being reversed.

The plugin stores a durable receipt with each successful mutation in the same
SQLite transaction. Exact command retries return the recorded result. Reusing
a command ID for different content is rejected, and concurrent commands use an
immediate transaction plus account revision checks.

## Dates, windows, and overrides

The configured IANA timezone determines the local family date, including across
daylight-saving and UTC boundaries. Recurring windows use ISO weekdays (Monday
is 1; Sunday is 7). A per-date override can classify a holiday or late-pickup
day as school/non-school and replace that day's eligibility window, or make the
day ineligible. Overrides never import or mutate Google Calendar data and do
not expose adult calendar details. The first slice retains at most 16 date
overrides so its transport-neutral detail snapshot remains bounded.

Startup TOML seeds the plugin only on its first activation. After that, the
plugin-owned SQLite settings edited in Rewards are authoritative; later TOML
changes do not silently overwrite parent edits. Recreate or migrate the plugin
database intentionally if a new declarative seed is required.

## Access and first-slice limits

Mission Control currently has a same-origin write token, not real parent/child
authentication. Treat the entire web application as an adult-operated surface
behind the existing loopback or access-controlled deployment boundary. This
feature does not add a child-facing board or widen network permissions.

This first slice also does not run a live countdown, stop a console, integrate
with Nintendo, or take earned credit back for a difficult stopping transition.
Those remain separate product and security decisions.
