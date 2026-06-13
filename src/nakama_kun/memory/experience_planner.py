from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from nakama_kun.memory.retriever import ExperienceBundle


class MemoryInsights(BaseModel):
    """Explainability metadata from long-term memory."""

    similar_task_found: bool = Field(default=False)
    prior_failure_detected: bool = Field(default=False)
    user_preference_applied: bool = Field(default=False)
    insights: list[str] = Field(default_factory=list)
    failure_prevention_hints: list[str] = Field(default_factory=list)


class ExperienceAwarePlanner:
    """Service that formats memory experiences for the planner and generates failure prevention hints."""

    def build_prompt_section(self, bundle: ExperienceBundle) -> str:
        """Formats the experience bundle as three detailed markdown sections for planner prompt injection."""
        sections = []

        # 1. Similar Successful Tasks
        if bundle.similar_successes:
            sections.append("### Similar Successful Tasks")
            seen = set()
            for s in bundle.similar_successes:
                goal_clean = s.goal.strip()
                if goal_clean not in seen:
                    seen.add(goal_clean)
                    sections.append(f"* Goal: {goal_clean}")
                    sections.append(f"  Files Changed: {', '.join(s.files_changed) if s.files_changed else '(none)'}")
                    sections.append(f"  Tools Used: {', '.join(s.tools_used) if s.tools_used else '(none)'}")
                    sections.append(f"  Outcome: {s.outcome.strip()}")
            sections.append("")

        # 2. Similar Failures
        if bundle.similar_failures:
            sections.append("### Similar Failures")
            seen = set()
            for f in bundle.similar_failures:
                goal_clean = f.goal.strip()
                if goal_clean not in seen:
                    seen.add(goal_clean)
                    sections.append(f"* Goal: {goal_clean}")
                    sections.append(f"  Failure Type: {f.failure_type}")
                    sections.append(f"  Root Cause: {f.failure_message.strip()}")
                    sections.append(f"  Resolution: {f.resolution.strip()}")
            sections.append("")

        # 3. User Preferences
        if bundle.user_preferences:
            sections.append("### User Preferences")
            # Sort by confidence descending
            sorted_prefs = sorted(bundle.user_preferences, key=lambda p: p.confidence, reverse=True)
            for p in sorted_prefs:
                sections.append(f"* {p.key}: {p.value} (confidence: {p.confidence:.2f})")
            sections.append("")

        return "\n".join(sections).strip()

    def build_failure_prevention_hints(self, bundle: ExperienceBundle) -> list[str]:
        """Scans similar failures for error patterns and returns proactive prevention steps."""
        hints = []
        seen_hints = set()

        for f in bundle.similar_failures:
            msg = f.failure_message.lower()
            res = f.resolution.lower()
            
            # ModuleNotFoundError or ImportError
            if "modulenotfounderror" in msg or "importerror" in msg or "pythonpath" in res or "import" in res:
                hint = "Verify import paths and PYTHONPATH configuration."
                if hint not in seen_hints:
                    seen_hints.add(hint)
                    hints.append(hint)
            
            # Test failure
            if "test_failure" in f.failure_type.lower() or "fail" in msg or "pytest" in res or "test" in res:
                hint = "Run test suites locally before submitting changes."
                if hint not in seen_hints:
                    seen_hints.add(hint)
                    hints.append(hint)
            
            # QA Rejection / Missing artifacts
            if "qa_rejection" in f.failure_type.lower() or "missing_artifacts" in f.failure_type.lower() or "artifact" in msg:
                hint = "Double check requirements checklist to prevent rejection."
                if hint not in seen_hints:
                    seen_hints.add(hint)
                    hints.append(hint)

        return hints

    def build_memory_insights(self, bundle: ExperienceBundle) -> MemoryInsights:
        """Constructs explanatory MemoryInsights metadata for the generated plan."""
        similar_task_found = len(bundle.similar_successes) > 0
        prior_failure_detected = len(bundle.similar_failures) > 0
        user_preference_applied = len(bundle.user_preferences) > 0

        insights = []
        if similar_task_found:
            insights.append(f"Similar task found in long-term memory ({len(bundle.similar_successes)} success(es)).")
        if prior_failure_detected:
            insights.append(f"Prior failure detected for a similar goal ({len(bundle.similar_failures)} failure(s)).")
        if user_preference_applied:
            insights.append(f"User preference applied ({len(bundle.user_preferences)} preference(s)).")

        hints = self.build_failure_prevention_hints(bundle)

        return MemoryInsights(
            similar_task_found=similar_task_found,
            prior_failure_detected=prior_failure_detected,
            user_preference_applied=user_preference_applied,
            insights=insights,
            failure_prevention_hints=hints,
        )
