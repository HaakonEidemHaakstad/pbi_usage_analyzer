"""Provider-agnostic core of the optional AI assistant (docs/AI_ASSISTANT_DESIGN.md).

Builds briefings, deterministic attempt assessments and prompts from an
`AnalysisResult`. Contains no network code and no AI SDK; transports live outside
the core package.
"""
from .attempt import (EFFECT_LABELS, AssessedChange, AttemptAssessment, Effect, RunCounts, assess_attempt,
                      run_counts)
from .briefing import BRIEFING_FORMAT, Briefing, BriefingSection, build_briefing
from .prompts import PROMPT_VERSION, SYSTEM_PROMPT, TASK_LABELS, Prompt, Task, build_prompt

__all__ = [
    "EFFECT_LABELS", "AssessedChange", "AttemptAssessment", "Effect", "RunCounts", "assess_attempt", "run_counts",
    "BRIEFING_FORMAT", "Briefing", "BriefingSection", "build_briefing",
    "PROMPT_VERSION", "SYSTEM_PROMPT", "TASK_LABELS", "Prompt", "Task", "build_prompt",
]
