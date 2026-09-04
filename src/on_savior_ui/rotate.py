"""Auto-rotate: thin a continuity's saves to fit a budget.

Rotation drops the saves whose removal costs the least detail, so history is
kept at full resolution near the present and progressively coarser the further
back you go.

For a candidate ``i``, removing it re-parents its children onto its parent, and
the play-time span that stops being recoverable is

    gap(i) = min(child play time, or i's own if it is a tip) − parent play time

The cost of losing that is discounted by how old the save is::

    cost(i) = gap(i) / (1 + age(i))       age(i) = newest play time − i's

Repeatedly dropping the cheapest candidate settles at a spacing proportional to
age — dense recent saves, sparse old ones — without needing hand-tuned tiers.

Nothing is removed that the policy protects: manual saves, starred saves, the
most recent N, the run's first save, forks, and the tip of every timeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .catalog import Continuity, SaveRef
from .store import RetentionPolicy, SaveMeta


@dataclass
class Decision:
    key: str
    name: str
    keep: bool
    reason: str
    size_bytes: int
    play_time: float

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "keep": self.keep,
            "reason": self.reason,
            "size_bytes": self.size_bytes,
            "play_time": self.play_time,
        }


@dataclass
class PrunePlan:
    continuity_id: str
    decisions: list[Decision] = field(default_factory=list)
    size_before: int = 0
    count_before: int = 0
    over_budget: bool = False
    """True when the budget could not be met without breaking a protection."""

    @property
    def remove(self) -> list[Decision]:
        return [d for d in self.decisions if not d.keep]

    @property
    def freed_bytes(self) -> int:
        return sum(d.size_bytes for d in self.remove)

    def as_dict(self) -> dict:
        return {
            "continuity_id": self.continuity_id,
            "size_before": self.size_before,
            "size_after": self.size_before - self.freed_bytes,
            "count_before": self.count_before,
            "count_after": self.count_before - len(self.remove),
            "freed_bytes": self.freed_bytes,
            "over_budget": self.over_budget,
            "remove": [d.as_dict() for d in self.remove],
            "decisions": [d.as_dict() for d in self.decisions],
        }


def _protections(
    group: Continuity,
    policy: RetentionPolicy,
    meta: dict[str, SaveMeta],
) -> dict[str, str]:
    """Saves rotation must not touch, mapped to why."""
    held: dict[str, str] = {}
    children = group.children()

    for ref in group.saves:
        if meta.get(ref.key, SaveMeta()).starred:
            held.setdefault(ref.key, "starred")
        if policy.keep_manual and not ref.is_autosave:
            held.setdefault(ref.key, "manual save")
        if group.parents.get(ref.key) is None:
            held.setdefault(ref.key, "start of the run")
        if policy.keep_branch_points:
            kids = children.get(ref.key, [])
            if len(kids) > 1:
                held.setdefault(ref.key, "fork point")
            elif not kids:
                held.setdefault(ref.key, "tip of a timeline")

    recent = sorted(group.saves, key=lambda r: r.created_epoch, reverse=True)
    for ref in recent[: max(policy.keep_recent, 0)]:
        held.setdefault(ref.key, f"one of the {policy.keep_recent} most recent")
    return held


def plan(
    group: Continuity,
    policy: RetentionPolicy,
    meta: dict[str, SaveMeta] | None = None,
) -> PrunePlan:
    """Work out which of a continuity's saves rotation would drop."""
    meta = meta or {}
    refs: dict[str, SaveRef] = {r.key: r for r in group.saves}
    sizes = {k: r.size_bytes for k, r in refs.items()}
    result = PrunePlan(
        continuity_id=group.id,
        size_before=sum(sizes.values()),
        count_before=len(refs),
    )

    held = _protections(group, policy, meta)
    parents = dict(group.parents)
    live = set(refs)
    dropped: dict[str, str] = {}

    newest_play = max((r.play_time for r in refs.values()), default=0.0)

    def over_budget() -> bool:
        if policy.max_bytes is not None:
            if sum(sizes[k] for k in live) > policy.max_bytes:
                return True
        if policy.max_count is not None:
            if len(live) > policy.max_count:
                return True
        return False

    def cost(key: str) -> float:
        parent = parents.get(key)
        lo = refs[parent].play_time if parent in refs else 0.0
        kids = [k for k in live if parents.get(k) == key]
        hi = min(refs[k].play_time for k in kids) if kids else refs[key].play_time
        age = max(newest_play - refs[key].play_time, 0.0)
        return max(hi - lo, 0.0) / (1.0 + age)

    while over_budget():
        candidates = [k for k in live if k not in held]
        if not candidates:
            result.over_budget = True
            break
        victim = min(candidates, key=lambda k: (cost(k), -refs[k].play_time))
        live.discard(victim)
        parent = parents.get(victim)
        for k in list(parents):
            if parents[k] == victim:
                parents[k] = parent
        dropped[victim] = "thinned — older history kept coarser"

    for ref in sorted(group.saves, key=lambda r: r.play_time):
        if ref.key in dropped:
            reason = dropped[ref.key]
        else:
            reason = held.get(ref.key, "within budget")
        result.decisions.append(
            Decision(
                key=ref.key,
                name=ref.name,
                keep=ref.key in live,
                reason=reason,
                size_bytes=sizes[ref.key],
                play_time=ref.play_time,
            )
        )
    return result
