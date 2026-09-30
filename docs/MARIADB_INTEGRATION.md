# MariaDB integration validation

## Purpose

MariaDB is an optional third validation layer:

1. unit/regression tests
2. synthetic PBIP/PBIR/TMDL fixtures with explicit ground truth
3. disposable database-backed integration tests

The database layer does not replace static fixtures. It is used where a real
relational source materially improves validation, for example source
architecture, connector assumptions and future query-folding investigations.

## Start

Copy the example environment file once:

    cd integration/mariadb
    copy .env.example .env

On PowerShell you can also run:

    .\scripts\integration-up.ps1

The first run creates `.env` and asks you to edit the two example database
passwords.

Then:

    docker compose up -d

or from the repository root:

    .\scripts\integration-up.ps1

## Stop

    .\scripts\integration-down.ps1

## Reset all synthetic database state

    .\scripts\integration-reset.ps1

This removes the volume and recreates the database from the SQL files under
`integration/mariadb/init/`.

## Connection

Default host:
    127.0.0.1

Default port:
    3307

Default database:
    pbi_validation

Default user:
    pbi_agent

The password is taken from the local `.env`.

## Data model

The seed database contains:
- dim_company
- dim_account
- dim_department
- fact_ledger
- ledger_2024
- vw_fact_ledger_narrow

This intentionally supports both sensible star-schema examples and test cases
for wide/imported/historical tables.

Only synthetic data belongs here.
