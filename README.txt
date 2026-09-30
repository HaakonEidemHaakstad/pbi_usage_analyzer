POWER BI USAGE ANALYZER — AGENTIC DEVELOPMENT EDITION
======================================================

This repository is intended to be opened as a project in VS Code.

Start here:
  AGENTS.md
  docs/DEVELOPMENT.md
  docs/architecture.md
  docs/ROADMAP.md

Windows quick start:
  powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1

Then run:
  python -m unittest discover -s tests -v


POWER BI USAGE ANALYZER V2
==========================

Dette er en ny, modulær versjon av analyseverktøyet for Power BI PBIP/PBIR-prosjekter.

Målet er å finne oppryddingskandidater i den semantiske modellen uten å feilaktig foreslå sletting av objekter som rapporten eller modellen trenger.

V2 er bygget rundt en eksplisitt dependency graph i stedet for at hver parser selv bestemmer om et objekt er brukt eller ubrukt.

ARKITEKTUR
----------

Analyseflyten er:

    PBIR + TMDL + DAX + relasjoner + hierarkier + Power Query/M
                              |
                              v
                       Dependency graph
                              |
                              v
                      Brukspropagering
                              |
                              v
                        Klassifisering
                              |
                 +------------+------------+
                 |                         |
                 v                         v
          TXT brukerrapport          Excel audit

Statusene er:

    Used
        Det finnes sterk evidens for at objektet er nødvendig.

    Needs manual review
        Det finnes en troverdig avhengighet eller referanse, men analysen kan ikke sikkert avgjøre om objektet er aktivt nødvendig.

    Likely unused
        Ingen kjent rapportbruk eller relevant avhengighet ble funnet.

    Internal / auto-generated
        Power BI-internt objekt.

"Likely unused" betyr ikke "garantert trygt å slette".

INSTALLASJON
------------

Python 3 kreves.

Installer avhengigheter:

    pip install -r requirements.txt

KJØRING
-------

Fra denne mappen:

    python run_analyzer.py "C:\sti\til\PBIP-prosjekt"

Hvis scriptet kjøres fra selve prosjektmappen:

    python run_analyzer.py .

Forventet prosjektstruktur er normalt:

    Prosjekt.pbip
    Prosjekt.Report\
    Prosjekt.SemanticModel\

OUTPUT
------

Verktøyet oppretter:

    <Prosjekt>_usage_summary_v2.txt
    <Prosjekt>_usage_analysis_v2.xlsx

VIKTIGE ANALYSEKILDER
---------------------

V2 undersøker blant annet:

- visual-, side- og rapportreferanser i PBIR
- measures og kolonner i TMDL
- DAX-avhengigheter
- relasjoner
- hierarkier
- Sort by column
- Power BI auto-date-objekter
- field parameters / NAMEOF der de kan identifiseres
- enkelte RLS/calculation-group-referanser
- Power Query/M-avhengigheter mellom spørringer
- rå PBIR-referanser som sikkerhetsnett

POWER QUERY / M
---------------

M-parseren skal bare trekke query-avhengigheter fra faktiske M-uttrykk i partisjonenes `source =`-blokker.

Eksempel:

    Table.Combine({#"Fjernede kolonner", #"Hovedbok 2024"})

skal gi:

    Hovedbok <- Hovedbok 2024

Et tabellnavn som bare finnes i metadata, DAX, en tekststreng eller kommentar skal ikke skape en Power Query-avhengighet.

V2 skiller mellom query-level og column-level lineage. En query-level dependency beskytter foreløpig upstream-kolonner konservativt som "Needs manual review". Det betyr ikke at alle kolonnene nødvendigvis er nødvendige.

NESTE PLANLAGTE FORBEDRING
--------------------------

Den viktigste videreutviklingen er kolonnenivå-lineage gjennom Power Query/M. Målet er å forstå transformasjoner som Table.SelectColumns, Table.RemoveColumns og Table.Combine slik at verktøyet kan avgjøre hvilke upstream-kolonner som faktisk propagere videre.

UTVIKLING
---------

Agent- og utviklingsreglene ligger i AGENT.md.

Kjør tester med:

    python -m unittest discover -s tests -v

Regresjonstestene skal utvides hver gang en ny feilklasse oppdages.


OPTIONAL MARIADB INTEGRATION
----------------------------
See:
  docs/MARIADB_INTEGRATION.md
  docs/PRIVILEGED_ACCESS.md

The MariaDB environment is disposable and Docker-based. Do not store a sudo
password in the repository or give the coding agent a reusable OS credential.

UBUNTU / VS CODE QUICK START
----------------------------
Ubuntu is now the primary development platform.

    make check
    make setup
    make test
    make validate

Optional MariaDB integration:

    make db-up
    make db-down
    make db-reset

See:
    docs/UBUNTU_SETUP.md

