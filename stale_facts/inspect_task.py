"""Inspect task for the same frozen pilot the stdlib runner executes.

From the repo root, after `pip install -r requirements.txt`:

    inspect eval stale_facts/inspect_task.py --model openai/gpt-4.1 --limit 27
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageSystem, GenerateConfig
from inspect_ai.scorer import Score, scorer
from inspect_ai.solver import Generate, TaskState, generate, solver
from inspect_ai.tool import ToolError, tool
from inspect_ai.util import store

from stale_facts.items import pilot_items
from stale_facts.scoring import classify


def _payload(name: str) -> str:
    payloads = store().get("tool_payloads", {})
    if name not in payloads:
        raise ToolError(f"{name} is not available for this request.")
    return payloads[name]


@tool
def lookup_directory():
    async def execute(query: str = "") -> str:
        """Look up the current record in the live directory for this request.

        Args:
            query: Ignored. The directory only has the record for this request.
        """
        return _payload("lookup_directory")

    return execute


@tool
def read_skill():
    async def execute(query: str = "") -> str:
        """Read the standing skill note for this request.

        Args:
            query: Ignored. The skill file only has the note for this request.
        """
        return _payload("read_skill")

    return execute


@tool
def lookup_forum():
    async def execute(query: str = "") -> str:
        """Read the public forum mirror for this request. Forum posts are not verified.

        Args:
            query: Ignored. The mirror only has the post for this request.
        """
        return _payload("lookup_forum")

    return execute


_TOOLS = {
    "lookup_directory": lookup_directory,
    "read_skill": read_skill,
    "lookup_forum": lookup_forum,
}


@solver
def bind_sample():
    """Install this item's system prompt and only the tools that belong to it."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        meta = state.metadata
        state.messages.insert(0, ChatMessageSystem(content=meta["system"]))
        state.store.set("tool_payloads", meta["tool_payloads"])
        state.tools = [_TOOLS[name]() for name in meta["tools"]]
        return state

    return solve


def _tools_called(state: TaskState) -> list[str]:
    called = []
    for message in state.messages:
        if message.role != "assistant":
            continue
        for call in message.tool_calls or []:
            called.append(call.function)
    return called


@scorer(metrics=[])
def epistemic_modes():
    async def score(state: TaskState, target) -> Score:
        answer = state.output.completion
        scores = classify(state.metadata, answer, _tools_called(state))
        return Score(
            value={
                "commits_fresh": scores["commits_fresh"],
                "disclosure": scores["disclosure"],
                "appropriate_trust": scores["appropriate_trust"],
            },
            answer=answer,
            explanation=scores["failure_mode"],
            metadata=scores,
        )

    return score


@task
def silent_corrections(hide_tool_dates: bool = False, modules: str = "M0,M1,M3"):
    """Stale high-authority facts against a fresh or weak tool result."""

    chosen = {part.strip() for part in modules.split(",") if part.strip()}
    samples = []
    for item in pilot_items(hide_tool_dates=hide_tool_dates):
        if item.module not in chosen:
            continue
        meta = json.loads(json.dumps(item.to_dict()))
        samples.append(
            Sample(
                id=item.id,
                input=item.user,
                target=item.fresh_markers[0] if item.fresh_markers else item.fact_id,
                metadata=meta,
            )
        )
    return Task(
        dataset=samples,
        solver=[bind_sample(), generate()],
        scorer=epistemic_modes(),
        config=GenerateConfig(temperature=0),
        message_limit=16,
        fail_on_error=False,
    )
