"""Config loading, validation, and the `{BASE}` templating / set-base mutation."""
import re

import yaml

IATA_RE = re.compile(r"^[A-Z]{3}$")


def resolve_base(obj, base):
    """Recursively replace the literal ``{BASE}`` in every string with ``base``."""
    if isinstance(obj, str):
        return obj.replace("{BASE}", base)
    if isinstance(obj, list):
        return [resolve_base(x, base) for x in obj]
    if isinstance(obj, dict):
        return {k: resolve_base(v, base) for k, v in obj.items()}
    return obj


def load_config(path="config.yaml"):
    """Load YAML config with ``{BASE}`` resolved to ``current_base`` throughout."""
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    base = cfg.get("current_base", "")
    return resolve_base(cfg, base)


def set_base(iata, path="config.yaml"):
    """Rewrite ``current_base`` in place. Validates a 3-letter IATA code."""
    iata = iata.strip().upper()
    if not IATA_RE.match(iata):
        raise ValueError(f"Not a valid IATA code: {iata!r}")
    with open(path) as f:
        raw = f.read()
    new, n = re.subn(r"(?m)^current_base:.*$", f"current_base: {iata}", raw, count=1)
    if n == 0:
        new = f"current_base: {iata}\n" + raw
    with open(path, "w") as f:
        f.write(new)


def validate_config(cfg):
    """Return a list of human-readable problems ([] == valid)."""
    problems = []
    if not IATA_RE.match(str(cfg.get("current_base", ""))):
        problems.append("current_base must be a 3-letter IATA code")
    for i, c in enumerate(cfg.get("corridors", []) or []):
        for req in ("origin", "destination"):
            if not c.get(req):
                problems.append(f"corridor[{i}] missing {req}")
    for i, w in enumerate(cfg.get("deadline_watches", []) or []):
        for req in ("destination", "must_arrive_by"):
            if not w.get(req):
                problems.append(f"deadline_watch[{i}] missing {req}")
    return problems
