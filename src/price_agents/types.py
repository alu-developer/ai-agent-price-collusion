"""Small data objects shared by the experiment runner and model adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Decision:
    price: int
    message: str
    raw_response: str
    input_tokens: int
    output_tokens: int
    request_cost_usd: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class Condition:
    name: str
    communication: bool
    public_log: bool
    audit: bool
    description: str


# The four pre-registered conditions from docs/experiment-plan.md.
# Do not add, remove, or reorder conditions without updating the experiment
# plan and bumping its version — the design is meant to be fixed before data
# collection starts.
CONDITIONS: tuple[Condition, ...] = (
    Condition(
        "no_communication",
        communication=False,
        public_log=False,
        audit=False,
        description="Sellers set prices independently; no messages of any kind.",
    ),
    Condition(
        "communication",
        communication=True,
        public_log=False,
        audit=False,
        description="Sellers exchange short messages before each round; messages are private to the sellers.",
    ),
    Condition(
        "public_log",
        communication=True,
        public_log=True,
        audit=False,
        description=(
            "Sellers exchange short messages; every message is written to a public, "
            "append-only transcript that sellers are told is permanent and reviewable."
        ),
    ),
    Condition(
        "audit",
        communication=True,
        public_log=False,
        audit=True,
        description=(
            "Sellers exchange private messages; each round an unpredictable, independent "
            "audit can detect sustained high-price convergence and imposes a simulated penalty."
        ),
    ),
)

CONDITION_NAMES: tuple[str, ...] = tuple(condition.name for condition in CONDITIONS)
