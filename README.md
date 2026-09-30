# Power BI Usage Analyzer

This repository is intended to be opened as a project in VS Code.

Start here:

- [AGENTS.md](AGENTS.md)
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/ROADMAP.md](docs/ROADMAP.md)

Windows quick start:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

Then run:

```shell
python -m unittest discover -s tests -v
```


## Power BI Usage Analyzer V2

Dette er en ny, modulær versjon av analyseverktøyet for Power BI PBIP/PBIR-prosjekter.

Målet er å finne oppryddingskandidater i den semantiske modellen uten å feilaktig foreslå sletting av objekter som rapporten eller modellen trenger.

V2 er bygget rundt en eksplisitt dependency graph i stedet for at hver parser selv bestemmer om et objekt er brukt eller ubrukt.

## Arkitektur

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

## Installasjon

Python 3 kreves. Ubuntu/Linux er primær utviklingsplattform.

Opprett et lokalt Python-miljø og installer avhengigheter:

```bash
make setup
```

Se [Ubuntu-oppsett](docs/UBUNTU_SETUP.md). Docker er valgfritt for vanlige tester, selv om `make check` rapporterer det som en manglende forutsetning.

## Kjøring

Fra denne mappen:

```bash
make analyze PROJECT="/sti/til/PBIP-prosjekt"
```

Alternativt, med prosjektets virtuelle Python-miljø:

```bash
.venv/bin/python run_analyzer.py "/sti/til/PBIP-prosjekt"
```

Forventet prosjektstruktur er normalt:

    Prosjekt.pbip
    Prosjekt.Report\
    Prosjekt.SemanticModel\

## Output

Verktøyet oppretter:

    <Prosjekt>_usage_summary_v2.txt
    <Prosjekt>_usage_analysis_v2.xlsx

## Viktige analysekilder

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

## Power Query / M

M-parseren skal bare trekke query-avhengigheter fra faktiske M-uttrykk i partisjonenes `source =`-blokker.

Eksempel:

    Table.Combine({#"Fjernede kolonner", #"Hovedbok 2024"})

skal gi:

    Hovedbok <- Hovedbok 2024

Et tabellnavn som bare finnes i metadata, DAX, en tekststreng eller kommentar skal ikke skape en Power Query-avhengighet.

Interne `LocalDateTable_*`- og `DateTableTemplate_*`-objekter holdes utenfor forretningstellingen. De beskytter bare konkret identifiserte kolonner gjennom relasjoner eller støttede `Table.SelectColumns`-uttrykk. Uavklart auto-date-lineage gir advarsler.

V2 skiller mellom query-level og column-level lineage. En query-level dependency fra en vanlig modelltabell beskytter foreløpig upstream-kolonner konservativt som "Needs manual review". Det betyr ikke at alle kolonnene nødvendigvis er nødvendige.

## Neste planlagte forbedring

Den viktigste videreutviklingen er kolonnenivå-lineage gjennom Power Query/M. Målet er å forstå transformasjoner som Table.SelectColumns, Table.RemoveColumns og Table.Combine slik at verktøyet kan avgjøre hvilke upstream-kolonner som faktisk propagerer videre.

## Utvikling

Agent- og utviklingsreglene ligger i [AGENTS.md](AGENTS.md).

Kjør tester med:

```bash
make compile
make test
make validate
```

Regresjonstestene skal utvides hver gang en ny feilklasse oppdages.


## Optional MariaDB integration

See:

- [docs/MARIADB_INTEGRATION.md](docs/MARIADB_INTEGRATION.md)
- [docs/PRIVILEGED_ACCESS.md](docs/PRIVILEGED_ACCESS.md)

The MariaDB environment is disposable and Docker-based. Do not store a sudo
password in the repository or give the coding agent a reusable OS credential.

## Ubuntu / VS Code quick start

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

- [docs/UBUNTU_SETUP.md](docs/UBUNTU_SETUP.md)
