"""Deterministic assessment of an attempt to improve a model: what changed between
two runs and whether each change is an improvement, a cleanup or a risk.

Shown next to the changes by the desktop app's Changes tab and given to the AI
assistant as fact, so the AI explains changes instead of guessing what a diff means.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from ..model import ObjectType, Status
from .history import Change, ChangeKind, RunSnapshot, compare_runs


class Effect(str, Enum):
    RISK = "risk"
    ATTENTION = "attention"
    IMPROVEMENT = "improvement"
    CLEANUP = "cleanup"
    NEUTRAL = "neutral"


EFFECT_LABELS = {
    Effect.RISK: "Risk",
    Effect.ATTENTION: "Attention",
    Effect.IMPROVEMENT: "Improvement",
    Effect.CLEANUP: "Cleanup",
    Effect.NEUTRAL: "Neutral",
}

# One line per rating, for legends and tooltips.
EFFECT_SUMMARIES = {
    Effect.RISK: "Something that was in use was removed or now refers to a missing object. Check it first.",
    Effect.ATTENTION: "Possibly unintended, for example an object that lost its use or a new finding.",
    Effect.IMPROVEMENT: "A model-health finding no longer occurs.",
    Effect.CLEANUP: "A Likely unused object was removed. Validate refresh and visuals.",
    Effect.NEUTRAL: "No action needed, for example a new object that is used.",
}

# Plural phrases for summaries such as "2 risks · 1 needs attention".
_COUNT_PHRASES = {
    Effect.RISK: ("risk", "risks"),
    Effect.ATTENTION: ("needs attention", "need attention"),
    Effect.IMPROVEMENT: ("improvement", "improvements"),
    Effect.CLEANUP: ("cleanup", "cleanups"),
    Effect.NEUTRAL: ("neutral", "neutral"),
}


def effect_summary(changes: Iterable[AssessedChange]) -> str:
    """`2 risks · 1 needs attention · 3 improvements`, most serious first; empty if none."""
    counts = Counter(item.effect for item in changes)
    return " · ".join(f"{counts[effect]} {_COUNT_PHRASES[effect][counts[effect] != 1]}"
                      for effect in Effect if counts[effect])


@dataclass(frozen=True)
class AssessedChange:
    change: Change
    effect: Effect
    note: str


@dataclass(frozen=True)
class RunCounts:
    columns: dict[Status, int]
    measures: dict[Status, int]
    findings_by_rule: dict[str, int]

    @property
    def findings(self) -> int:
        return sum(self.findings_by_rule.values())


@dataclass(frozen=True)
class AttemptAssessment:
    before_analyzed_at: str
    before: RunCounts
    after: RunCounts
    # Most serious first (Effect order), then in compare_runs order.
    changes: tuple[AssessedChange, ...]

    def of(self, effect: Effect) -> tuple[AssessedChange, ...]:
        return tuple(item for item in self.changes if item.effect == effect)


def run_counts(run: RunSnapshot) -> RunCounts:
    def statuses(kind: ObjectType) -> dict[Status, int]:
        counts = Counter(state.status for key, state in run.objects.items()
                         if key.split("|", 1)[0] == kind.value)
        return {status: counts[status] for status in Status}

    rules = Counter(state.rule_id for state in run.findings.values())
    return RunCounts(statuses(ObjectType.COLUMN), statuses(ObjectType.MEASURE), dict(sorted(rules.items())))


def _assess(change: Change, before: RunSnapshot, after: RunSnapshot) -> tuple[Effect, str]:
    kind = change.kind
    if kind == ChangeKind.FINDING_RESOLVED:
        return Effect.IMPROVEMENT, "The rule no longer reports this."
    if kind == ChangeKind.FINDING_ADDED:
        if after.findings[change.key].rule_id == "DAX_REFERENCE_UNRESOLVED":
            return Effect.RISK, ("DAX now refers to a column or measure that does not exist. This usually "
                                 "follows removing or renaming an object that was in use; visuals using "
                                 "the expression will show errors.")
        return Effect.ATTENTION, "New finding since the previous analysis."
    if kind == ChangeKind.OBJECT_REMOVED:
        old = before.objects[change.key].status
        if old == Status.USED:
            return Effect.RISK, ("The previous analysis proved this object used. Check that visuals, DAX "
                                 "and relationships still work.")
        if old == Status.MANUAL_REVIEW:
            return Effect.ATTENTION, ("This object needed a manual decision. Confirm that refresh and "
                                      "visuals still work.")
        if old == Status.LIKELY_UNUSED:
            return Effect.CLEANUP, ("Removed a cleanup candidate. Validate refresh and visuals in Power BI "
                                    "Desktop; other reports on the same semantic model are not visible to "
                                    "the analyzer.")
        return Effect.NEUTRAL, "Auto-generated object removed (for example after turning off Auto date/time)."
    if kind == ChangeKind.OBJECT_ADDED:
        new = after.objects[change.key].status
        if new == Status.LIKELY_UNUSED:
            return Effect.ATTENTION, "New object that nothing uses yet."
        return Effect.NEUTRAL, "New object."
    old, new = before.objects[change.key].status, after.objects[change.key].status
    if Status.INTERNAL in (old, new):
        return Effect.NEUTRAL, "Status of an auto-generated object changed."
    if new == Status.LIKELY_UNUSED:
        return Effect.ATTENTION, ("No known use any more. If this was not intended, a visual, measure or "
                                  "relationship that used it may have been removed.")
    if old == Status.USED and new == Status.MANUAL_REVIEW:
        return Effect.ATTENTION, "Lost its proven use; only unproven evidence of use remains."
    if new == Status.USED:
        return Effect.NEUTRAL, "Now proven used."
    return Effect.NEUTRAL, "Now has credible but unproven evidence of use."


def assess_attempt(before: RunSnapshot, after: RunSnapshot) -> AttemptAssessment:
    order = list(Effect)
    assessed = []
    for change in compare_runs(before, after):
        effect, note = _assess(change, before, after)
        assessed.append(AssessedChange(change, effect, note))
    assessed.sort(key=lambda item: order.index(item.effect))  # stable: keeps compare_runs order
    return AttemptAssessment(before.analyzed_at, run_counts(before), run_counts(after), tuple(assessed))
