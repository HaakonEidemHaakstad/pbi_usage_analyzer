# AI assistant design — Power BI Model Health Analyzer

Status: proposed 2026-10-05; phase A0 (core briefing, attempt assessment, prompts)
implemented. This document fixes the architecture and scope of the optional AI
layer (AGENTS.md, "Future AI layer"; ROADMAP Phase 5).

Owner decisions (2026-10-05):

- The assistant should (1) interpret the results of an analysis, (2) suggest next
  steps towards best practice, and (3) evaluate the results of attempts to improve
  the model. Development is iterative.
- Model provider: **Claude (Anthropic)**, through the organization's agreement.
  Which platform (Anthropic API, Amazon Bedrock, Google Vertex AI, Microsoft
  Foundry) and how users authenticate is still open (section 12).
- Data scope: **everything in the analysis** may be sent, including DAX and M
  expressions, file names and server names.
- First iteration: this design plus an offline, tested core (phase A0).

## 1. Goal

Turn the analyzer's deterministic output into advice a Power BI developer can act
on: what the findings mean together, what to do first, and whether a change made
the model better or worse. The assistant adds judgement and explanation; it adds
no analysis. Dependencies, statuses and rule findings still come only from
`analyze_project()`.

## 2. Users and tasks

Same primary user as the GUI: the person who maintains the model, working in Power
BI Desktop, re-running the analyzer after each change.

| Task | Input | Output |
| --- | --- | --- |
| Interpret | One analysis | The overall picture, the important findings grouped by theme, what the counts do and do not mean, limits of the analysis. |
| Next steps | One analysis (plus acknowledgements) | A short prioritized plan; each step says what to do, why, which findings it addresses and what the next analysis should show. |
| Evaluate an attempt | Current analysis, previous run, deterministic assessment, optionally the previous advice | What improved, what regressed, anything risky (first), whether the planned effects happened, what to do next. |

## 3. Principles

1. **Advisory and above the analysis.** The AI reads a briefing built from
   `AnalysisResult`; it never parses PBIP files and never decides a status.
2. **Deterministic first.** Anything that can be computed is computed in the core
   and given to the AI as fact: run comparison and the risk classification of each
   change (`assistant.attempt`) work without AI and can be shown by any front end.
3. **Conservatism survives the AI.** The system prompt carries the status
   semantics and the Likely-unused caveat. The assistant must never call an object
   safe to delete, must keep Needs manual review as a human decision, and must
   label its own opinions as such.
4. **Grounded.** The assistant refers to objects as `Table[Name]` and to findings by
   rule ID and scope, exactly as in the briefing, and says when the briefing does
   not contain what a question needs. A later phase checks cited names against the
   result (section 9).
5. **Project content is data, not instructions.** Names, descriptions, DAX and M come
   from the user's files and may contain text that looks like an instruction. The
   briefing is wrapped in `<analysis>` tags and the system prompt says to treat it
   as data.
6. **The core stays offline.** `pbi_usage_analyzer.assistant` builds text; it has no
   network code and no SDK dependency (tested by an import guard). Network access
   lives only in an optional transport package and a separate app build (section 7).
7. **Read-only.** The assistant never edits the project. Changes are made in Power BI
   Desktop and verified by re-running the analysis.

## 4. Architecture

```
pbi_usage_analyzer/                core, no network (unchanged rule)
  views/history.py                 snapshot(), compare_runs()  (existing)
  assistant/                       A0: UI- and provider-agnostic
    briefing.py                    AnalysisResult (+ previous run, acknowledgements) -> Briefing
    attempt.py                     previous run + current run -> AttemptAssessment
    prompts.py                     Task, system prompt, build_prompt() -> Prompt
pbi_usage_analyzer_ai/             A2: optional transport (anthropic SDK)
  claude.py                        Prompt -> streamed answer
pbi_usage_analyzer_gui/            A1/A3: Assistant panel (copy prompt, then live answers)
```

Flow:

```
analyze_project()  ->  AnalysisResult
                          |  + previous RunSnapshot, acknowledgements
                          v
                  build_briefing()  ->  Briefing (sections, deterministic text)
                          v
            build_prompt(task, briefing, question, prior_advice)  ->  Prompt(system, user)
                          v
       transport: copy and paste (A1)  |  Claude API (A2)
```

`Prompt` is plain data (system text, user text, task, prompt version), so a front
end can show it, copy it, store it with an answer, or hand it to a transport.

## 5. Briefing

`build_briefing(result, *, previous=None, acknowledgements=None,
include_expressions=True)` returns a `Briefing` of titled sections with stable
keys. Rendering is deterministic: the same result gives byte-identical text (no
timestamps except the previous run's own; no absolute paths; source files are shown
relative to the project root). That makes it testable and keeps the prompt prefix
cacheable (section 7).

| Section | Content |
| --- | --- |
| `project` | Name, analyzer version, counts of tables, columns, measures, relationships, queries, findings, diagnostics; health filter note if a filter was applied. |
| `cleanup` | Likely-unused count per table. (Status counts are in `project`; status meanings and the caveat are in the system prompt, taken from `views.catalog.STATUS_INFO`.) |
| `health` | Findings grouped by rule (severity, name, rule ID, category, rule summary); per finding scope, title, confidence, location, evidence; explanation and recommendation once per rule when all its findings share them. |
| `likely_unused` | Likely-unused objects by table, with type, hidden/calculated flags and data type. |
| `manual_review` | Objects needing review, with their reasons and evidence path. |
| `diagnostics` | Code, severity, location and message. |
| `structure` | Business tables with column/measure counts per status; relationships with cardinality, direction and active state (relationships to auto-date tables only counted); M queries by kind; query dependencies. |
| `expressions` | Measure and calculated-column DAX; M of partitions, shared queries and parameters. Omitted with `include_expressions=False`. |
| `acknowledged` | Items the user has reviewed, with notes: decided, not to be raised as new. |
| `changes` | Only with a previous run: counts before and after, and every change with its deterministic assessment, most serious first. |

Used objects are summarized per table rather than listed (their DAX is in
`expressions`). Internal auto-date objects are counted, never listed as
candidates. Sizes measured on the case studies are recorded in section 13.

Nothing is truncated silently. If a briefing ever exceeds what a model accepts,
the front end must say so and offer `include_expressions=False`, not cut text.

## 6. Attempt assessment (deterministic)

`assess_attempt(before, after)` compares two `RunSnapshot`s with `compare_runs` and
gives each change an effect and a note:

| Change | Effect |
| --- | --- |
| Object removed that was **Used** | Risk: the previous run proved it used; check visuals, DAX and relationships. |
| New `DAX_REFERENCE_UNRESOLVED` finding | Risk: DAX now refers to a missing object, typically after removing or renaming one. |
| Object removed that needed manual review | Attention: it needed a decision; confirm refresh and visuals. |
| Status became Likely unused (was Used or review) | Attention: no known use any more; intended? |
| Used became Needs manual review | Attention: lost its proven use. |
| New health finding (other rules) | Attention. |
| New object nothing uses | Attention. |
| Health finding resolved | Improvement. |
| Likely-unused object removed | Cleanup (validate refresh and visuals in Desktop). |
| Anything else (now used, new used object, auto-generated object added/removed) | Neutral. |

The assessment also carries status counts and findings per rule for both runs. It
is useful without AI (the GUI's Changes tab can show the effects) and gives the AI
facts to explain instead of a diff to interpret.

## 7. Transport

**A1, copy and paste (no network in the app).** The app shows the prompt and copies
it to the clipboard; the user pastes it into Claude under the organization's
agreement and can paste the answer back to keep it with the run. This works with the
current network-free build and IT fact sheet unchanged.

**A2, Claude API (optional package and separate build).**

- Package `pbi_usage_analyzer_ai` with the official `anthropic` Python SDK as an
  optional extra (`pip install .[ai]`). The core never imports it.
- The standard Windows build stays network-free (`check_bundle.py` keeps failing on
  network components). An "assistant" build variant includes TLS and the SDK, gets
  its own IT fact-sheet section, and is only produced when IT has accepted it.
- Model `claude-opus-5-5` by default (configurable). Adaptive thinking (always on
  for this model), `output_config.effort` set explicitly (`high` for next steps and
  evaluation, `medium` for interpretation, to be tuned on the eval set), streaming
  with the SDK's final-message helper, `max_tokens` about 16,000.
- Prompt caching: the system prompt and the briefing form a stable prefix; follow-up
  questions about the same run are appended after it. A changed analysis gives a new
  briefing and a new cache entry, which is expected.
- `stop_reason` is checked before reading content (`refusal`, `max_tokens`), the
  request ID is kept for support, and SDK errors are shown as structured, retryable
  or not; no silent retries beyond the SDK's own.
- Credentials are never stored in the project, settings files or logs. The
  platform decides the mechanism (API key from the environment or Windows
  Credential Manager; AWS/GCP/Entra sign-in for Bedrock/Vertex/Foundry), which is
  why the platform choice is an open question.

## 8. Output format

- Interpretation and evaluation: Markdown prose with short sections.
- Next steps: numbered steps `S1`, `S2`, ... each with *Do*, *Why*, *Addresses*
  (rule IDs and scopes, `Table[Name]`), *Expect in the next analysis* and *Risk /
  validate*. In A2 this becomes structured output (JSON schema), stored with the run
  so that evaluation can check each step's expected effect against the actual
  changes deterministically.

## 9. Testing and quality

- Core (A0): unit tests on synthetic scenarios: section content, determinism,
  relative paths, expressions toggle, the caveat in every prompt, assessment effects
  for each change kind, and an import guard (no `anthropic`, `httpx`, `http.client`,
  `urllib.request`, `socket` after importing the assistant package).
- No network in the test suite. Transport tests (A2) use a fake client.
- Answer quality (A3): an eval set built from the case studies with known ground
  truth. AW Mess must produce advice that covers its documented bad practices; AW
  Good must not invent problems (specificity, as for the rules). Graded per item:
  cites only names that exist, never suggests deleting Used or review objects,
  covers the important findings. Changing the prompt or model means re-running it.
- A post-check (A3) resolves every `Table[Name]` and rule ID in an answer against
  the result and flags unknown names to the user.

## 10. Phases

| Phase | Content |
| --- | --- |
| A0 | This document; `assistant` package: briefing, attempt assessment, prompts; tests. **Done.** |
| A1 | GUI Assistant panel and CLI option: choose a task, optional question, show and copy the prompt; Changes tab shows assessment effects; paste an answer back and keep it with the run. No network. |
| A2 | `pbi_usage_analyzer_ai` Claude transport, settings for model/effort/credentials, streamed answers in the panel, separate build variant and IT documentation. Needs the platform decision. |
| A3 | Follow-up questions per run, stored plans with deterministic expected-effect checks, answer post-check, eval set from the case studies. |

## 11. Non-goals

- No AI parsing of PBIP files, and no AI-decided statuses or rule findings.
- No automatic edits to the project, no generated scripts that delete objects.
- No telemetry; nothing is sent without an explicit user action.
- No other providers unless the owner decides otherwise.

## 12. Open questions

1. Claude platform and authentication (Anthropic API key, Bedrock, Vertex, Foundry)
   and whether the organization's agreement covers project metadata, DAX and M.
2. Will IT accept a network-enabled build variant, or should A1 copy-and-paste remain
   the only route on managed PCs?
3. Answer language: English by default (the interface language); the assistant
   follows the language of the user's question.

## 13. A0 result

Implemented 2026-10-05 in `pbi_usage_analyzer/assistant/`:

- `briefing.py`: `build_briefing`, `Briefing` (`sections`, `section(key)`, `text()`,
  `assessment`), `BRIEFING_FORMAT = 1`.
- `attempt.py`: `assess_attempt`, `AttemptAssessment` (`changes` most serious first,
  `of(effect)`, before/after `RunCounts`), `Effect`, `EFFECT_LABELS`.
- `prompts.py`: `Task`, `TASK_LABELS`, `SYSTEM_PROMPT`, `build_prompt` -> `Prompt`
  (`system`, `user`, `text()` for pasting), `PROMPT_VERSION = 1`.
- `views.explain.review_reason` (moved from the text report, unchanged behaviour) so
  the briefing and the text report give the same manual-review reasons.

Sizes measured on the real projects (characters; roughly four per token):

| Project | Briefing | Without expressions |
| --- | --- | --- |
| AW Mess | 44,600 | 30,700 |
| AdventureWorks | 41,100 | 23,600 |
| AW Good | 10,600 | 2,600 |

The system prompt is about 3,300 characters. A prompt is therefore around 12,000
tokens for the larger case studies, small compared with the model's context.

Tests: `tests/test_assistant.py` (21: effects per change kind, an end-to-end removal of
a used column giving two risks, sections, determinism across folders, no absolute
paths, owner status in review reasons, auto-date relationship summary, filter note,
acknowledgements, changes section, prompt order and safety text, evaluation needs a
previous run, offline import guard). No analysis change, no GUI change, no network
code. Not yet tried against a live model: the prompts' wording is a first draft
to be tuned with the A3 eval set.
