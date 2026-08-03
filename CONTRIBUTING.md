# Contributing

Mission Control favors small, reviewable vertical slices.

## Development

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest
python -m ruff check .
bash scripts/check-schemas.sh
nix flake check
```

## Design expectations

- preserve a functional core and imperative shell
- parse untrusted data into precise immutable values
- keep authoritative domain values valid by construction
- use explicit states and closed tagged variants
- keep JSON as the stable machine interface
- keep renderers incapable of state mutation
- route commands to exactly one authoritative owner
- keep CUE as the canonical language-neutral public-contract source
- do not add a framework or abstraction without a demonstrated requirement

Generated schemas must be regenerated and checked for drift whenever their CUE
sources change.
