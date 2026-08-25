from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CapabilitySpec:
    name: str
    adapter: str
    read_only: bool
    requires_approval: bool
    consumes: str | None = None
    enabled: bool = False


REGISTRY = {
    "check_status": CapabilitySpec(
        name="check_status",
        adapter="cli",
        read_only=True,
        requires_approval=False,
        enabled=True,
    ),
    "sync_positions": CapabilitySpec(
        name="sync_positions",
        adapter="cli",
        read_only=True,
        requires_approval=False,
        enabled=True,
    ),
    "recommend_candidates": CapabilitySpec(
        name="recommend_candidates",
        adapter="cli",
        read_only=True,
        requires_approval=False,
        enabled=True,
    ),
    "search_candidates": CapabilitySpec(
        name="search_candidates",
        adapter="cli",
        read_only=True,
        requires_approval=False,
        consumes="search",
        enabled=True,
    ),
    "greet": CapabilitySpec(
        name="greet",
        adapter="cli",
        read_only=False,
        requires_approval=True,
        consumes="contact",
        enabled=True,
    ),
    "request_resume": CapabilitySpec(
        name="request_resume",
        adapter="cli",
        read_only=False,
        requires_approval=False,
        consumes="message",
        enabled=True,
    ),
    "view_online_resume": CapabilitySpec(
        name="view_online_resume",
        adapter="playwright",
        read_only=False,
        requires_approval=True,
        consumes="resume_view",
        enabled=True,
    ),
    "send_interview": CapabilitySpec(
        name="send_interview",
        adapter="playwright",
        read_only=False,
        requires_approval=True,
        consumes="message",
        enabled=True,
    ),
    "deep_match": CapabilitySpec(
        name="deep_match",
        adapter="cli",
        read_only=False,
        requires_approval=True,
        consumes="deep_match",
        enabled=True,
    ),
    "sync_conversations": CapabilitySpec(
        name="sync_conversations",
        adapter="cli",
        read_only=True,
        requires_approval=False,
        enabled=True,
    ),
    "search_pull_resumes": CapabilitySpec(
        name="search_pull_resumes",
        adapter="cli",
        read_only=True,
        requires_approval=False,
        consumes="search",
        enabled=True,
    ),
}


def capability_payload():
    return {name: asdict(spec) for name, spec in REGISTRY.items()}
