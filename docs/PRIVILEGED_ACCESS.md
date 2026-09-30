# Privileged access and secrets

## Do not store a sudo password in this repository

Do not place the user's sudo password in:
- AGENTS.md
- `.env`
- VS Code settings
- shell scripts
- source code
- test fixtures
- git configuration
- plain-text files intended for an agent

An agent that can read the repository would then possess a reusable login
credential. This is unnecessary for normal development and creates a much
larger security boundary than this project needs.

## Preferred approach

Design the local development environment so routine agent work does not need
sudo at all.

For this repository that means:
- Python work happens inside `.venv`
- MariaDB integration tests use Docker Compose
- the database contains synthetic data only
- credentials in `integration/mariadb/.env` are service credentials for the
  disposable test database, not the user's operating-system password
- `.env` is gitignored

If Docker is already usable by the current account, no sudo is required.

On Linux, prefer rootless Docker or another rootless container runtime when
practical.

If a one-time machine-level setup really requires administrator privileges,
the user should perform that setup interactively rather than handing the
agent a reusable sudo password.

## If narrowly scoped passwordless privilege is truly required

Only after reviewing the exact command, configure a least-privilege sudoers
rule for a specific executable and argument pattern. Do not grant blanket:

    ALL=(ALL) NOPASSWD: ALL

and do not give an agent unrestricted root access merely for convenience.

Any sudoers change should be:
- explicit
- minimal
- reviewed by the user
- reversible
- unrelated to production credentials or organizational systems

## Database secrets

`integration/mariadb/.env` is intentionally local-only.

Use random development-only passwords. They protect only the disposable local
validation database and should never be reused elsewhere.
