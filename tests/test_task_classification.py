import pytest
from nakama_kun.orchestration.task_classifier import TaskType, TaskClassifier, classify_task

def test_task_type_comparisons():
    """Verify that TaskType enum comparison is case-insensitive and backward compatible with string checks."""
    assert TaskType.RETRIEVAL == "RETRIEVAL"
    assert TaskType.RETRIEVAL == "retrieval"
    assert "RETRIEVAL" == TaskType.RETRIEVAL
    assert "retrieval" == TaskType.RETRIEVAL

    assert TaskType.CODE_MODIFICATION == "CODE_MODIFICATION"
    assert TaskType.CODE_MODIFICATION == "code_modification"
    assert "CODE_MODIFICATION" == TaskType.CODE_MODIFICATION

    # Also test inequality
    assert TaskType.RETRIEVAL != "ANALYSIS"
    assert TaskType.RETRIEVAL != "analysis"
    assert "ANALYSIS" != TaskType.RETRIEVAL

    # String representation
    assert str(TaskType.RETRIEVAL) == "retrieval"
    assert str(TaskType.CODE_MODIFICATION) == "code_modification"


def test_classify_task_analysis():
    """Verify that analysis-oriented tasks are correctly classified."""
    analysis_goals = [
        "Analyze repository",
        "Review architecture",
        "Explain implementation",
        "Audit codebase",
        "Summarize project",
    ]
    for goal in analysis_goals:
        assert classify_task(goal) == TaskType.ANALYSIS


def test_classify_task_documentation():
    """Verify that documentation-oriented tasks are correctly classified."""
    doc_goals = [
        "Generate README",
        "Create architecture document",
        "Write migration guide",
        "Produce documentation",
        "Update README",
        "Modify README",
    ]
    for goal in doc_goals:
        assert classify_task(goal) == TaskType.DOCUMENTATION


def test_classify_task_code_modification():
    """Verify that code modification tasks are correctly classified."""
    code_mod_goals = [
        "Fix bug",
        "Add feature",
        "Refactor implementation",
        "Modify behavior",
        "Fix login bug",
        "Implement feature",
    ]
    for goal in code_mod_goals:
        assert classify_task(goal) == TaskType.CODE_MODIFICATION


def test_classify_mixed_requests():
    """Verify that mixed requests prioritize code modification."""
    mixed_goals = [
        "Update README and implement feature X",
        "Write migration guide and fix login bug",
        "Modify README and refactor implementation",
    ]
    for goal in mixed_goals:
        assert classify_task(goal) == TaskType.CODE_MODIFICATION


def test_classify_fallback():
    """Verify that unknown/empty tasks fallback to code modification."""
    assert classify_task("") == TaskType.CODE_MODIFICATION
    assert classify_task("unrelated random text") == TaskType.CODE_MODIFICATION


def test_classifier_metadata():
    """Verify TaskClassifier service returns structured metadata (confidence, reason)."""
    classifier = TaskClassifier()
    task_type, confidence, reason = classifier.classify("Fix login bug")
    assert task_type == TaskType.CODE_MODIFICATION
    assert confidence > 0.0
    assert "code_modification" in reason
