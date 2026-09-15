# Contributing

This project is a reproducible robotics-debugging prototype. Keep a change
small, explain its evidence, and preserve prior experiment results.

## Before committing

Run the credential-free test suite from Ubuntu in WSL:

```bash
cd "$(git rev-parse --show-toplevel)"
PYTHONPATH=src python3 -B -m unittest discover -s tests -v
```

Use a Conventional Commit message, for example
`feat(records): add replay attempt records` or
`test(reduce): cover exhausted budget`.

## Data and credentials

Do not commit access tokens, SSH private keys, `.env` files, model weights,
datasets, recordings, SQLite databases, or cloud logs containing secrets.
Store large run artifacts outside Git and include their revision, location, and
replay instructions in the relevant experiment record instead.

Do not classify an unavailable model server, invalid scene, or infrastructure
error as a policy failure. Preserve retries as separate attempts rather than
overwriting a previous result.
