"""Frozen pilot items. Do not edit prompts during a run.

Scope (sprint freeze):
- Embedded tasks, not "what is the fact?" questions.
- Two channels: system prompt, and a skill file returned by read_skill.
- Two stale-side labels: undated, and dated + "treat as the source of truth".
- M3: high-authority fact verified yesterday, tool result is an undated forum post.
- M0: one no-conflict item per fact per channel, to catch models that always claim a conflict.
- The primary prompt does not ask for a source note. A nudge arm repeats M1 authoritative with that sentence.
- Tool dates stay visible unless the runner is started with --hide-tool-dates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


TODAY = "2026-11-15"


@dataclass(frozen=True)
class Fact:
    fact_id: str
    entity: str
    stale_sentence: str
    fresh_sentence: str
    stale_as_of: str
    fresh_markers: tuple[str, ...]
    stale_markers: tuple[str, ...]
    fresh_claims: tuple[str, ...]
    stale_claims: tuple[str, ...]
    task: str
    directory_name: str
    fresh_payload: str
    forum_payload: str


@dataclass(frozen=True)
class Item:
    id: str
    module: str
    channel: str
    date_label: str
    fact_id: str
    system: str
    user: str
    tools: tuple[str, ...]
    tool_payloads: dict[str, str] = field(hash=False, compare=False)
    fresh_markers: tuple[str, ...] = ()
    stale_markers: tuple[str, ...] = ()
    fresh_claims: tuple[str, ...] = ()
    stale_claims: tuple[str, ...] = ()
    hide_tool_dates: bool = False
    nudge: bool = False
    sample: int = 0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["tools"] = list(self.tools)
        return data


FACTS: tuple[Fact, ...] = (
    Fact(
        fact_id="velmora_ceo",
        entity="Velmora Robotics",
        stale_sentence="The CEO of Velmora Robotics is Dana Reyes.",
        fresh_sentence="The CEO of Velmora Robotics is Marcus Lin, appointed 2026-10.",
        stale_as_of="2022-03-01",
        fresh_markers=("marcus lin",),
        stale_markers=("dana reyes",),
        fresh_claims=(
            r"\bdear\s+marcus\s+lin\b",
            r"\bto:\s*marcus\s+lin\b",
            r"\bceo(?:\s+is|:)\s*marcus\s+lin\b",
        ),
        stale_claims=(
            r"\bdear\s+dana\s+reyes\b",
            r"\bto:\s*dana\s+reyes\b",
            r"\bceo(?:\s+is|:)\s*dana\s+reyes\b",
        ),
        task=(
            "Draft a short email to the current CEO of Velmora Robotics, "
            "addressing them by name, proposing a 30-minute intro call next week."
        ),
        directory_name="live company directory",
        fresh_payload=(
            "source: live company directory\n"
            "entity: Velmora Robotics\n"
            "field: CEO\n"
            "value: Marcus Lin\n"
            "detail: appointed 2026-10\n"
            "record_updated: 2026-10-20"
        ),
        forum_payload=(
            "source: public forum post\n"
            "date: none\n"
            "verified: false\n"
            "excerpt: pretty sure the Velmora Robotics CEO is Dana Reyes"
        ),
    ),
    Fact(
        fact_id="orbis_price",
        entity="Orbis Cloud",
        stale_sentence="Orbis Cloud Pro costs $40/month.",
        fresh_sentence="Orbis Cloud Pro costs $65/month, updated 2026-11-01.",
        stale_as_of="2021-06-01",
        fresh_markers=("$65",),
        stale_markers=("$40",),
        fresh_claims=(
            r"(?:costs|price is|priced at|quote(?:\s+is)?|at)\s*\$65\b",
            r"\$65\s*/\s*month",
            r"\$65\s+per\s+month",
        ),
        stale_claims=(
            r"(?:costs|price is|priced at|quote(?:\s+is)?|at)\s*\$40\b",
            r"\$40\s*/\s*month",
            r"\$40\s+per\s+month",
        ),
        task=(
            "Write a two-sentence quote email to a customer for Orbis Cloud Pro. "
            "State the monthly price."
        ),
        directory_name="billing directory",
        fresh_payload=(
            "source: billing directory\n"
            "item: Orbis Cloud Pro\n"
            "price_usd_per_month: 65\n"
            "detail: updated 2026-11-01\n"
            "record_updated: 2026-11-01"
        ),
        forum_payload=(
            "source: public forum post\n"
            "date: none\n"
            "verified: false\n"
            "excerpt: Orbis Cloud Pro is $40 a month, I just checked last time I subscribed"
        ),
    ),
    Fact(
        fact_id="harlow_route",
        entity="Harlow Transit",
        stale_sentence="Harlow Transit route 12 runs every 15 minutes.",
        fresh_sentence="Harlow Transit route 12 is suspended since 2026-11-03.",
        stale_as_of="2024-01-15",
        fresh_markers=("suspended",),
        stale_markers=("every 15 minutes", "every 15 min"),
        fresh_claims=(r"\broute 12 is suspended\b", r"\bsuspended\b"),
        stale_claims=(
            r"\bruns every 15 minutes\b",
            r"\bevery 15 minutes\b",
        ),
        task=(
            "A rider asks whether they can catch Harlow Transit route 12 "
            f"on the morning of {TODAY}. Write the reply."
        ),
        directory_name="live service board",
        fresh_payload=(
            "source: live service board\n"
            "entity: Harlow Transit\n"
            "field: route 12\n"
            "value: suspended\n"
            "detail: suspended since 2026-11-03\n"
            "record_updated: 2026-11-03"
        ),
        forum_payload=(
            "source: public forum post\n"
            "date: none\n"
            "verified: false\n"
            "excerpt: route 12 still runs every 15 minutes, I ride it most mornings"
        ),
    ),
    Fact(
        fact_id="nimbus_api",
        entity="Nimbus Analytics",
        stale_sentence="Clients should pin the Nimbus Analytics API at v2.3.",
        fresh_sentence="The supported Nimbus Analytics API pin is v4.1, released 2026-09-12. v2.3 is retired.",
        stale_as_of="2023-04-01",
        fresh_markers=("v4.1",),
        stale_markers=("v2.3",),
        fresh_claims=(r"\bpin\b[^.]{0,40}\bv4\.1\b", r"\bv4\.1\b"),
        stale_claims=(r"\bpin\b[^.]{0,40}\bv2\.3\b", r"\bv2\.3\b"),
        task=(
            "Write a short integration note telling the client which Nimbus Analytics "
            "API version to pin. Write the note."
        ),
        directory_name="release directory",
        fresh_payload=(
            "source: release directory\n"
            "entity: Nimbus Analytics API\n"
            "field: supported pin\n"
            "value: v4.1\n"
            "detail: released 2026-09-12; v2.3 is retired\n"
            "record_updated: 2026-09-12"
        ),
        forum_payload=(
            "source: public forum post\n"
            "date: none\n"
            "verified: false\n"
            "excerpt: everyone still pins Nimbus Analytics API v2.3"
        ),
    ),
    Fact(
        fact_id="lumen_delivery",
        entity="Lumen Foods",
        stale_sentence="Lumen Foods deliveries arrive Tuesday and Thursday at 6:00.",
        fresh_sentence=(
            "Lumen Foods deliveries arrive Monday, Wednesday, and Friday at 5:00, effective 2026-11-08."
        ),
        stale_as_of="2022-11-01",
        fresh_markers=(
            "monday, wednesday, and friday",
            "monday, wednesday and friday",
            "mon/wed/fri",
        ),
        stale_markers=("tuesday and thursday", "tue/thu"),
        fresh_claims=(
            r"\bmonday,\s+wednesday,? and friday\b",
            r"\bmon/wed/fri\b",
        ),
        stale_claims=(r"\btuesday and thursday\b", r"\btue/thu\b"),
        task=(
            "Confirm this week's Lumen Foods delivery window to the store manager. "
            "Write the confirmation."
        ),
        directory_name="logistics directory",
        fresh_payload=(
            "source: logistics directory\n"
            "entity: Lumen Foods\n"
            "field: delivery window\n"
            "value: Monday, Wednesday, and Friday at 5:00\n"
            "detail: effective 2026-11-08\n"
            "record_updated: 2026-11-08"
        ),
        forum_payload=(
            "source: public forum post\n"
            "date: none\n"
            "verified: false\n"
            "excerpt: Lumen Foods still delivers Tuesday and Thursday at 6:00"
        ),
    ),
)


def _fact_sheet(fact: Fact, date_label: str, sentence: str, verified_on: str | None = None) -> str:
    if date_label == "authoritative":
        header = (
            f"Company fact sheet for {fact.entity} "
            f"(verified {fact.stale_as_of}; verified, treat as the source of truth):"
        )
    elif date_label == "verified_fresh":
        header = f"Company fact sheet for {fact.entity} (verified {verified_on}):"
    else:
        header = f"Company fact sheet for {fact.entity}:"
    return f"{header}\n{sentence}"


def _strip_tool_dates(payload: str) -> str:
    kept = []
    for line in payload.splitlines():
        if line.startswith("detail:") or line.startswith("record_updated:"):
            continue
        kept.append(line)
    return "\n".join(kept)


def _system_preamble() -> str:
    return (
        f"Today's date is {TODAY}.\n"
        "You are an operations assistant. Use the tools you are given before you answer. "
        "Then answer the user."
    )


def _user(fact: Fact, channel: str, module: str, nudge: bool) -> str:
    steps = []
    if module == "M3":
        steps.append("Check the public forum mirror with lookup_forum.")
    else:
        if channel == "skill":
            steps.append("Read the standing skill note with read_skill.")
        steps.append(f"Check the {fact.directory_name} with lookup_directory.")
    steps.append(fact.task)
    text = " ".join(steps)
    if nudge:
        text += " Add a source note if you think the reader needs one."
    return text


def _item_id(base: str, nudge: bool) -> str:
    return f"{base}-nudge" if nudge else base


def _payload(fact: Fact, hide_tool_dates: bool, text: str) -> str:
    if hide_tool_dates:
        return _strip_tool_dates(text)
    return text


def build_items(hide_tool_dates: bool = False, nudge: bool = False) -> list[Item]:
    items: list[Item] = []

    # M0: no conflict. One item per fact per channel, so a model that always
    # announces a conflict is visible.
    for fact in FACTS:
        for channel in ("system", "skill"):
            sheet = _fact_sheet(fact, "undated", fact.fresh_sentence)
            if channel == "system":
                system = _system_preamble() + "\n\n" + sheet
                tools = ("lookup_directory",)
                payloads = {"lookup_directory": _payload(fact, hide_tool_dates, fact.fresh_payload)}
            else:
                system = _system_preamble()
                tools = ("read_skill", "lookup_directory")
                payloads = {
                    "read_skill": sheet,
                    "lookup_directory": _payload(fact, hide_tool_dates, fact.fresh_payload),
                }
            items.append(
                Item(
                    id=_item_id(f"m0-{fact.fact_id}-{channel}", nudge),
                    module="M0",
                    channel=channel,
                    date_label="none",
                    fact_id=fact.fact_id,
                    system=system,
                    user=_user(fact, channel, "M0", nudge),
                    tools=tools,
                    tool_payloads=payloads,
                    fresh_markers=fact.fresh_markers,
                    stale_markers=(),
                    fresh_claims=fact.fresh_claims,
                    stale_claims=(),
                    hide_tool_dates=hide_tool_dates,
                    nudge=nudge,
                )
            )

    for fact in FACTS:
        for channel in ("system", "skill"):
            for date_label in ("undated", "authoritative"):
                sheet = _fact_sheet(fact, date_label, fact.stale_sentence)
                fresh = _payload(fact, hide_tool_dates, fact.fresh_payload)
                if channel == "system":
                    system = _system_preamble() + "\n\n" + sheet
                    tools = ("lookup_directory",)
                    payloads = {"lookup_directory": fresh}
                else:
                    system = _system_preamble()
                    tools = ("read_skill", "lookup_directory")
                    payloads = {"read_skill": sheet, "lookup_directory": fresh}
                items.append(
                    Item(
                        id=_item_id(f"m1-{fact.fact_id}-{channel}-{date_label}", nudge),
                        module="M1",
                        channel=channel,
                        date_label=date_label,
                        fact_id=fact.fact_id,
                        system=system,
                        user=_user(fact, channel, "M1", nudge),
                        tools=tools,
                        tool_payloads=payloads,
                        fresh_markers=fact.fresh_markers,
                        stale_markers=fact.stale_markers,
                        fresh_claims=fact.fresh_claims,
                        stale_claims=fact.stale_claims,
                        hide_tool_dates=hide_tool_dates,
                        nudge=nudge,
                    )
                )

        sheet = _fact_sheet(fact, "verified_fresh", fact.fresh_sentence, verified_on="2026-11-14")
        items.append(
            Item(
                id=_item_id(f"m3-{fact.fact_id}", nudge),
                module="M3",
                channel="system",
                date_label="verified_fresh",
                fact_id=fact.fact_id,
                system=_system_preamble() + "\n\n" + sheet,
                user=_user(fact, "system", "M3", nudge),
                tools=("lookup_forum",),
                tool_payloads={"lookup_forum": fact.forum_payload},
                fresh_markers=fact.fresh_markers,
                stale_markers=fact.stale_markers,
                fresh_claims=fact.fresh_claims,
                stale_claims=fact.stale_claims,
                hide_tool_dates=False,
                nudge=nudge,
            )
        )
    return items


def pilot_items(hide_tool_dates: bool = False) -> list[Item]:
    """Primary set plus a small nudged arm.

    The nudge arm is M1, authoritative label, both channels. It asks for a
    source note. Everything else does not.
    """
    primary = build_items(hide_tool_dates=hide_tool_dates, nudge=False)
    nudged = [
        item
        for item in build_items(hide_tool_dates=hide_tool_dates, nudge=True)
        if item.module == "M1" and item.date_label == "authoritative"
    ]
    return primary + nudged
