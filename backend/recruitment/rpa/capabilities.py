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
    "greet": CapabilitySpec(
        name="greet",
        adapter="cli",
        read_only=False,
        requires_approval=True,
        consumes="contact",
    ),
    "request_resume": CapabilitySpec(
        name="request_resume",
        adapter="cli",
        read_only=False,
        requires_approval=True,
        consumes="message",
    ),
    "view_online_resume": CapabilitySpec(
        name="view_online_resume",
        adapter="playwright",
        read_only=False,
        requires_approval=True,
        consumes="resume_view",
    ),
    "send_interview": CapabilitySpec(
        name="send_interview",
        adapter="playwright",
        read_only=False,
        requires_approval=True,
        consumes="message",
    ),
    "deep_match": CapabilitySpec(
        name="deep_match",
        adapter="cli",
        read_only=False,
        requires_approval=True,
        consumes="deep_match",
    ),
}


def capability_payload():
    return {name: asdict(spec) for name, spec in REGISTRY.items()}
