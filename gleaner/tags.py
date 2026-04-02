"""Session classification tags.

Derives `source` and `task_type` from session metadata. Used at upload
time (stored in Firestore) and at pull time (added to Parquet).
"""

# Kodo-generated topic patterns (these are kodo regardless of host/project)
_KODO_TOPIC_TASKS = {
    "swe_bench": lambda t: "Fix the following" in t,
    "merge_conflict": lambda t: t.startswith("Resolve the merge conflicts"),
    "verification": lambda t: t.startswith("The orchestrator claims"),
    "commit": lambda t: t.startswith("Review `git diff`") and "commit" in t.lower(),
    "analysis": lambda t: t.startswith("Analyze this project"),
}


def tag_session(
    project: str, topic: str, host: str, cwd: str, *, ide: str = "claude_code"
) -> dict[str, str]:
    """Classify a session by source and task type.

    Args:
        ide: Which IDE produced this session ("claude_code" or "cursor").

    Returns {"source": ..., "task_type": ..., "ide": ...}.
    """
    # Check if topic matches a kodo-generated pattern
    kodo_task = None
    for task, matches in _KODO_TOPIC_TASKS.items():
        if matches(topic):
            kodo_task = task
            break

    # source
    is_tmp_path = "private-var" in project or project.startswith("-root")
    is_kodo_project = "kodo" in project.lower() or is_tmp_path
    is_kodo_host = not cwd and host == "openclaw-1"
    is_kodo = is_kodo_project or is_kodo_host or kodo_task is not None or "instance_" in project
    # Cursor benchmark runs are kodo-driven
    if ide == "cursor" and "kodo-benchmark" in project:
        is_kodo = True

    if project == "gleaner-e2e":
        source = "test"
    elif is_kodo:
        source = "kodo"
    else:
        source = "human"

    # task_type
    if kodo_task:
        task_type = kodo_task
    elif "instance_" in project:
        task_type = "swe_bench"
    elif ide == "cursor" and "kodo-benchmark" in project:
        task_type = "swe_bench"
    elif project == "gleaner-e2e":
        task_type = "test"
    elif is_tmp_path and source == "kodo":
        task_type = "kodo_harness"
    elif source == "kodo":
        task_type = "kodo_other"
    else:
        task_type = "development"

    return {"source": source, "task_type": task_type, "ide": ide}
