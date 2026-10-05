# Local machine notes (template)

Copy this file to `LOCAL.md` (ignored by git) and fill it in for your computer.
`LOCAL.md` holds facts about one machine: absolute paths, installed tools and where
things live. Committed docs must not contain them. Never put passwords or tokens in
either file. Agents read `LOCAL.md` when it exists (AGENTS.md).

Machine: <name / OS>. Last checked: <date>.

## Repository and Python

- Clone: `<path to the repository>`
- Python: <version(s)>; `.venv` created with `scripts/bootstrap.ps1` (or `make setup`).
- Extra packages in `.venv` that are not project requirements: <none / list>.
- Tools available: make <yes/no>, Docker <yes/no>.

## Test projects (integration tests)

| What | Path | Environment variable |
| --- | --- | --- |
| AdventureWorks (course PBIP) | `<path>` | `PBI_AW_PROJECT` |
| AW Mess case study | `<path>` | `PBI_AW_MESS_PROJECT` |
| AW Good case study | `<path>` | `PBI_AW_GOOD_PROJECT` |

## Case-study sources

- `<WORK>` in the case-study docs = `<base folder holding AW, the sources and the PBIP projects>`.
- Mess sources: `<path>` (the AW Mess M steps hard-code this path).
- Good-twin sources: `<path>`.

## MariaDB (case-study databases)

- Version, service name, client path, ODBC driver: <...>

## Windows app

- Installed copy: `<path to the "PBI Model Health" folder>`
- Build output folder: `<path outside any synced folder>`

## Claude Desktop (MCP server)

- Config file: `<path to claude_desktop_config.json>` (Microsoft Store builds keep
  it under `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude`).
- Entry: `<command and args>`
- Logs: `<path>`

## Shell cautions on this machine

- <...>
