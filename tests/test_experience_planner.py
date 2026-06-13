from __future__ import annotations

import os
import tempfile
from datetime import datetime, UTC
import pytest

from nakama_kun.memory.models import SuccessfulTask, FailureRecord, UserPreference
from nakama_kun.memory.sqlite_store import SQLiteMemoryStore
from nakama_kun.memory.retriever import ExperienceBundle
from nakama_kun.memory.experience_planner import ExperienceAwarePlanner
from nakama_kun.memory.feedback import MemoryFeedbackService


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


def test_planner_receives_memory_context():
    """Verify that build_prompt_section produces all required memory structures."""
    bundle = ExperienceBundle(
        similar_successes=[
            SuccessfulTask(
                goal="Create FastAPI server",
                plan_summary="Init app.py",
                files_changed=["app.py"],
                tools_used=["write_file"],
                outcome="FastAPI is working",
                timestamp=datetime.now(UTC),
            )
        ],
        similar_failures=[
            FailureRecord(
                goal="Run test suite",
                attempted_actions=["run_command(pytest)"],
                failure_type="TEST_FAILURE",
                failure_message="ModuleNotFoundError: No module named 'fastapi'",
                resolution="Install fastapi",
                timestamp=datetime.now(UTC),
            )
        ],
        user_preferences=[
            UserPreference(
                key="linter",
                value="ruff",
                confidence=0.9,
                source="user_goal",
                updated_at=datetime.now(UTC),
            )
        ]
    )

    planner = ExperienceAwarePlanner()
    prompt = planner.build_prompt_section(bundle)

    # Verify successes section
    assert "### Similar Successful Tasks" in prompt
    assert "Goal: Create FastAPI server" in prompt
    assert "Files Changed: app.py" in prompt
    assert "Tools Used: write_file" in prompt
    assert "Outcome: FastAPI is working" in prompt

    # Verify failures section
    assert "### Similar Failures" in prompt
    assert "Goal: Run test suite" in prompt
    assert "Failure Type: TEST_FAILURE" in prompt
    assert "Root Cause: ModuleNotFoundError: No module named 'fastapi'" in prompt
    assert "Resolution: Install fastapi" in prompt

    # Verify preferences section
    assert "### User Preferences" in prompt
    assert "linter: ruff (confidence: 0.90)" in prompt


def test_planner_uses_successful_examples():
    """Verify successes are formatted cleanly and deduplicated in prompt."""
    task1 = SuccessfulTask(
        goal="Setup logging",
        plan_summary="Add log.py",
        files_changed=["log.py"],
        tools_used=["write_file"],
        outcome="Logger is up",
    )
    task2 = SuccessfulTask(
        goal="Setup logging",
        plan_summary="Add log.py",
        files_changed=["log.py"],
        tools_used=["write_file"],
        outcome="Logger is up",
    )

    bundle = ExperienceBundle(
        similar_successes=[task1, task2],
        similar_failures=[],
        user_preferences=[]
    )

    planner = ExperienceAwarePlanner()
    prompt = planner.build_prompt_section(bundle)

    assert "### Similar Successful Tasks" in prompt
    # Since they are identical goals, we expect deduplication by goal in build_prompt_section
    assert prompt.count("Goal: Setup logging") == 1


def test_planner_avoids_known_failures():
    """Verify build_failure_prevention_hints recognizes common failure keywords."""
    f1 = FailureRecord(
        goal="Setup project",
        attempted_actions=["run_command"],
        failure_type="TEST_FAILURE",
        failure_message="ModuleNotFoundError: No module named 'utils'",
        resolution="Add PYTHONPATH=src",
    )
    f2 = FailureRecord(
        goal="Run checks",
        attempted_actions=["run_command"],
        failure_type="TEST_FAILURE",
        failure_message="AssertionError in test_app.py",
        resolution="Fix test asserts",
    )
    f3 = FailureRecord(
        goal="Save file",
        attempted_actions=["write_file"],
        failure_type="QA_REJECTION",
        failure_message="Missing required artifact: docs.md",
        resolution="Add docs.md",
    )

    bundle = ExperienceBundle(
        similar_successes=[],
        similar_failures=[f1, f2, f3],
        user_preferences=[]
    )

    planner = ExperienceAwarePlanner()
    hints = planner.build_failure_prevention_hints(bundle)

    # Verify ModuleNotFoundError maps to PYTHONPATH hint
    assert "Verify import paths and PYTHONPATH configuration." in hints
    # Verify TEST_FAILURE maps to test validation hint
    assert "Run test suites locally before submitting changes." in hints
    # Verify QA_REJECTION maps to checklist hint
    assert "Double check requirements checklist to prevent rejection." in hints


def test_preferences_influence_planning():
    """Verify preferences are ordered by confidence in the formatted section."""
    p1 = UserPreference(key="typing", value="strict", confidence=0.4, source="user_goal")
    p2 = UserPreference(key="linter", value="ruff", confidence=0.9, source="user_goal")
    p3 = UserPreference(key="framework", value="fastapi", confidence=0.7, source="user_goal")

    bundle = ExperienceBundle(
        similar_successes=[],
        similar_failures=[],
        user_preferences=[p1, p2, p3]
    )

    planner = ExperienceAwarePlanner()
    prompt = planner.build_prompt_section(bundle)

    assert "### User Preferences" in prompt
    lines = [line for line in prompt.split("\n") if "confidence:" in line]
    assert len(lines) == 3
    # Check sorting: highest confidence (0.90) first, then 0.70, then 0.40
    assert "linter" in lines[0]
    assert "framework" in lines[1]
    assert "typing" in lines[2]


def test_memory_feedback_updates_statistics(temp_db):
    """Verify that MemoryFeedbackService increments frequencies and updates confidences in SQLite."""
    store = SQLiteMemoryStore(temp_db)
    feedback_service = MemoryFeedbackService(store)

    # 1. Test success frequency increment
    task = SuccessfulTask(
        goal="Test goal",
        plan_summary="Summary",
        files_changed=[],
        tools_used=[],
        outcome="Outcome",
        success_frequency=0
    )
    store.save_success(task)

    # Verify initial frequency is 0
    loaded = store.get_successes()[0]
    assert loaded.success_frequency == 0

    # Record usage
    feedback_service.record_success_usage("Test goal")
    # Verify it incremented to 1
    loaded = store.get_successes()[0]
    assert loaded.success_frequency == 1

    # 2. Test failure frequency increment
    failure = FailureRecord(
        goal="Test failure goal",
        attempted_actions=[],
        failure_type="QA_REJECTION",
        failure_message="Rejected",
        resolution="Resolve",
        failure_frequency=0
    )
    store.save_failure(failure)

    # Verify initial frequency is 0
    loaded_fail = store.get_failures()[0]
    assert loaded_fail.failure_frequency == 0

    # Record failure usage
    feedback_service.record_failure_usage("Test failure goal")
    loaded_fail = store.get_failures()[0]
    assert loaded_fail.failure_frequency == 1

    # 3. Test preference confidence boost
    pref = UserPreference(
        key="test_key",
        value="test_val",
        confidence=0.5,
        source="user_goal",
        updated_at=datetime.now()
    )
    store.save_preference(pref)

    # Boost confidence
    feedback_service.boost_preference_confidence("test_key", delta=0.1)
    loaded_pref = store.get_preferences()[0]
    assert abs(loaded_pref.confidence - 0.6) < 1e-5

    # Test confidence capping at 1.0
    feedback_service.boost_preference_confidence("test_key", delta=0.5)
    loaded_pref = store.get_preferences()[0]
    assert loaded_pref.confidence == 1.0


def test_memory_insights_explainability():
    """Verify that build_memory_insights sets flag values and constructs insights correctly."""
    bundle = ExperienceBundle(
        similar_successes=[
            SuccessfulTask(goal="A", plan_summary="B", files_changed=[], tools_used=[], outcome="C")
        ],
        similar_failures=[
            FailureRecord(goal="X", attempted_actions=[], failure_type="F", failure_message="M", resolution="R")
        ],
        user_preferences=[
            UserPreference(key="K", value="V", confidence=0.8, source="S")
        ]
    )

    planner = ExperienceAwarePlanner()
    insights = planner.build_memory_insights(bundle)

    assert insights.similar_task_found is True
    assert insights.prior_failure_detected is True
    assert insights.user_preference_applied is True
    assert len(insights.insights) == 3
    assert "Similar task found in long-term memory" in insights.insights[0]
    assert "Prior failure detected for a similar goal" in insights.insights[1]
    assert "User preference applied" in insights.insights[2]


def test_empty_bundle_safe():
    """Verify that empty/null bundle values do not cause crashes and output defaults."""
    bundle = ExperienceBundle()
    planner = ExperienceAwarePlanner()

    prompt = planner.build_prompt_section(bundle)
    assert prompt == ""

    hints = planner.build_failure_prevention_hints(bundle)
    assert hints == []

    insights = planner.build_memory_insights(bundle)
    assert insights.similar_task_found is False
    assert insights.prior_failure_detected is False
    assert insights.user_preference_applied is False
    assert insights.insights == []
    assert insights.failure_prevention_hints == []
