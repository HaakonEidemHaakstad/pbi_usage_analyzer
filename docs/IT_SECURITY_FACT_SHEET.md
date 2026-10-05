# PBI Model Health — IT security fact sheet

For IT and security reviewers deciding whether the desktop app may be used.
It states what the app does on a PC, what it does not do, how it is built, and the
known gaps. Everything here can be checked against the source code and the build
files listed at the end.

## What it is

A Windows desktop tool for Power BI developers. It reads a Power BI project
(PBIP: a folder of text files saved by Power BI Desktop) and reports which
columns and measures the report uses, which ones are probably unused, and common
model problems. It is a static analyzer: it reads definitions (table and column
names, DAX formulas, Power Query/M code, relationships, report page layouts) and
never data.

- About 6,000 lines of Python in two packages (`pbi_usage_analyzer`, the
  analysis; `pbi_usage_analyzer_gui`, the window). Desktop UI built with Qt for
  Python (PySide6).
- Distributed as a zip with a self-contained folder (`PBI Model Health.exe` plus
  an `_internal` folder with the Python runtime and libraries). Packaged with
  PyInstaller. `pbi-model-health-cli.exe` in the same folder is a console version
  that writes the reports for projects given on its command line (or dropped onto
  it), without a window; it behaves as described below.

## Behaviour on the PC

| Area | Behaviour |
| --- | --- |
| Installation | None. Unzip and run; no installer, no admin rights, no services, no scheduled tasks, no autostart, no shell extensions. |
| Privileges | Runs as the signed-in user with that user's file permissions. |
| Network | Makes no network connections. The app's code contains no network, download or upload calls, no telemetry and no update check. The build removes Qt's network module, its TLS and network-information plugins, and Python's TLS support (`_ssl`, `libssl`), and fails if any of them reappear (`packaging/check_bundle.py`). Python's basic `socket` module remains as part of the runtime; the app does not use it. |
| Data sources | Never connects to databases, files or services referenced by the Power BI model. Needs no credentials. |
| Files read | Only the selected project folder: the report and semantic-model definition files. It does not read the local data cache (`.pbi\cache.abf`). |
| Files written | Only (1) reports the user explicitly exports, to a folder the user chooses, or, if the user turns on *Write reports automatically* or uses the console version, a text and an Excel report in the project folder or a folder given with `--out`; and (2) one small JSON file per project analyzed in the window, with the last result and the user's review notes, in `%APPDATA%\pbi-usage-analyzer\Power BI Model Health Analyzer\projects\`. It never modifies the Power BI project's own files. |
| Registry | Recent-projects list and window settings under `HKEY_CURRENT_USER\Software\pbi-usage-analyzer`. Nothing machine-wide. |
| Claude Desktop (optional) | Only if the user adds it to Claude Desktop's configuration: Claude Desktop starts `pbi-model-health-cli.exe --mcp` and exchanges JSON messages with it over standard input/output (Model Context Protocol). The analyzer still makes no network connections; it answers tool calls the user approves in Claude Desktop (analyze a project, explain an object, save a baseline, compare with it). Its only extra file is one baseline per project in `%APPDATA%\pbi-usage-analyzer\Power BI Model Health Analyzer\assistant\`. Organizations can disable local MCP servers with Claude Desktop's `isLocalDevMcpEnabled` policy. |
| Other programs | Starts no processes. When the user clicks a file link, Windows opens that file with its default application (for example a `.tmdl` file in a text editor). |
| Code execution | Does not execute DAX, M or any code from the project; it parses text. No plug-ins, no scripting, no `eval`. |
| Removal | Delete the app folder, the `%APPDATA%\pbi-usage-analyzer` folder and the registry key above. |

## Data handled

Power BI project files contain metadata, not data rows: table and column names,
business logic (DAX, M), server and database names and file paths used by
queries. They do not contain passwords; Power BI stores data-source credentials
separately. The app keeps all of this on the PC. Exception: when the user connects
it to Claude Desktop, the tool results the user approves (briefings with names,
findings, paths, server names and, by default, DAX and M) go to Claude through
Claude Desktop, under the organization's agreement for that app.

Exports: the text and Excel reports contain object names, statuses and findings
(which can quote paths and server names). The optional JSON export also contains
the full DAX and M expressions; the app warns before writing it. Treat exports
like the project files themselves.

## Build and supply chain

- **Source:** a private GitHub repository. IT can review it and build the app
  itself (below).
- **Automated checks on every change:** about 290 unit, regression and GUI tests,
  a synthetic validation suite, and a build of the Windows app that is
  smoke-tested headlessly before its zip is published as a build artifact (kept
  14 days) together with `SHA256SUMS.txt`.
- **Pinned dependencies:** the app build installs from `requirements-build.lock`,
  which pins every package (direct and indirect) to one version with SHA-256
  hashes (`pip install --require-hashes`).
- **Bundled components:** Python, pandas, numpy, openpyxl (Excel export) and
  their dependencies, and Qt (PySide6). All are widely used open source; licences
  are in `THIRD_PARTY_NOTICES.txt` and `LICENSES\`. Qt is used under the LGPL v3
  with its libraries as separate, replaceable files.
- **In the app folder:** `sbom.cdx.json` (CycloneDX 1.5 SBOM of the bundled
  runtime with versions and package URLs) and `MANIFEST-SHA256.txt` (SHA-256 of
  every file, usable for allowlisting or integrity checks).

## Known gaps

1. **Not code-signed.** SmartScreen warns on first start, and application
   control policies (AppLocker, WDAC) block unsigned executables. Recommended:
   sign it with the organisation's code-signing certificate, or build it
   internally (below).
2. **Antivirus heuristics.** Executables packaged with PyInstaller are
   occasionally flagged by antivirus heuristics although harmless. Signing or an
   internal build usually resolves this; the manifest and SBOM help an analyst
   check the contents.
3. **No independent security review.** The code was largely written with an AI
   coding assistant under the owner's direction. It is small, reviewable, has no
   network or execution features and is covered by automated tests, but it has
   not had an independent security review.
4. **Ownership and licence.** The repository has no licence file yet and is held
   on a personal GitHub account. Internal use may need an agreement on ownership
   and terms.
5. **Maintenance.** Bundled libraries need updating when security fixes appear:
   regenerate the lock file (`pip-compile --generate-hashes`), rebuild and
   re-test. An owner for that should be agreed.

## Recommended way to approve it

Build and sign it internally, so the organisation trusts code it has seen, built
with tools it controls:

1. Review the source (the two packages above; `packaging/` and
   `scripts/build_windows.ps1` for the build).
2. On a build machine with Python 3.12 or newer:
   `python -m venv .venv`, then
   `.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-build.lock`,
   then `powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1 -OutDir <folder>`.
   The script builds the app, checks the bundle, runs the smoke test and writes
   the zip and `SHA256SUMS.txt`.
3. Sign `PBI Model Health.exe` (for example with `signtool sign`) and distribute
   the folder.

To observe the behaviour independently, run the app in Windows Sandbox or a test
VM with Process Monitor and a network monitor while analyzing a sample project.

## Where to check each statement

| Statement | Evidence |
| --- | --- |
| No network or process calls in the app code | `pbi_usage_analyzer/`, `pbi_usage_analyzer_gui/` (search for `socket`, `urllib`, `http`, `subprocess`) |
| Network components removed from the bundle | `packaging/pbi_model_health.spec`, `packaging/check_bundle.py` |
| Files and registry written | `pbi_usage_analyzer/reporting/files.py`, `pbi_usage_analyzer/views/history.py`, `pbi_usage_analyzer_gui/main_window.py`, `pbi_usage_analyzer_mcp/tools.py` (baseline) |
| Claude Desktop connection is stdio only | `pbi_usage_analyzer_mcp/protocol.py`; import guard in `tests/test_mcp_server.py` |
| Pinned, hash-checked build dependencies | `requirements-build.lock`, `.github/workflows/ci.yml` |
| SBOM and manifest | `packaging/write_notices.py`; `sbom.cdx.json`, `MANIFEST-SHA256.txt` in the app folder |
