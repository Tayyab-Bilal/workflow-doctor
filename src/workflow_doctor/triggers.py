"""Natural phrase -> trigger type. Shared by the extractor prompt and by any planner that picks triggers.

A test pins this map to the catalog in both directions: every mapped type must exist, and every
catalog trigger must be reachable from at least one phrase. A new engine trigger therefore fails
CI until someone maps it, instead of being silently unbuildable.
"""

from __future__ import annotations

TRIGGER_MAP: dict[str, str] = {
    "a task is created": "TaskCreated",
    "a new task is added": "TaskCreated",
    "a task becomes overdue": "TaskOverdue",
    "a task is late": "TaskOverdue",
    "a task is completed": "TaskCompleted",
    "a task is marked done": "TaskCompleted",
    "a task is assigned": "TaskAssigned",
    "someone is given a task": "TaskAssigned",
    "a comment is added": "CommentAdded",
    "someone comments": "CommentAdded",
    "a meeting is scheduled": "MeetingScheduled",
    "a meeting is booked": "MeetingScheduled",
    "a meeting ends": "MeetingEnded",
    "a meeting is over": "MeetingEnded",
    "a document is uploaded": "DocumentUploaded",
    "a file is uploaded": "DocumentUploaded",
    "a document is approved": "DocumentApproved",
    "a document is signed off": "DocumentApproved",
    "a project is created": "ProjectCreated",
    "a new project starts": "ProjectCreated",
    "a project is archived": "ProjectArchived",
    "a project is closed": "ProjectArchived",
    "someone joins a project": "MemberJoined",
    "a new member joins": "MemberJoined",
}


def resolve_trigger(phrase: str) -> str | None:
    """Trigger type for a phrase, or None. Matching is case- and space-insensitive."""
    return TRIGGER_MAP.get(" ".join(phrase.lower().split()))
