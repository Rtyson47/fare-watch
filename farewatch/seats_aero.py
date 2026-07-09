"""Optional seats.aero Pro award-space module — STUB, behind ``awards.enabled``.

Disabled by default (returns []). When you enable it, implement against the
Pro API *cached availability* endpoints only, capped at <=1000 calls/day using
the same guardrail pattern as ``spend`` (env SEATS_AERO_API_KEY).
"""
import logging

log = logging.getLogger("farewatch.seats_aero")


def check_award_space(corridor, cfg, client=None):
    """Return award-availability records for a corridor, or [] when disabled."""
    if not (cfg.get("awards") or {}).get("enabled"):
        return []
    # TODO(Phase 2): call seats.aero cached availability; enforce <=1000/day cap;
    # normalize to a small dataclass; surface on the dashboard.
    raise NotImplementedError("seats.aero award module is not implemented yet.")
