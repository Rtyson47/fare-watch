"""Terminal summary: per-corridor cheapest, deadline watches, inspiration, alerts, spend."""
from . import dashboard


def build_report(conn, cfg, today):
    data = dashboard.build_data(conn, cfg, today)
    lines = [f"fare-watch — base {data.get('base')} — {today.isoformat()}", ""]

    lines.append("Corridors:")
    if not data["corridors"]:
        lines.append("  (none configured)")
    for c in data["corridors"]:
        ch = c.get("current_cheapest")
        if ch:
            lines.append(f"  {c['route']}: cheapest {ch['price']:.0f}"
                         f" (dep {ch['depart_date']})  threshold {c['threshold']}")
        else:
            lines.append(f"  {c['route']}: no fares recorded yet  threshold {c['threshold']}")

    lines += ["", "Deadline watches:"]
    if not data["deadline_watches"]:
        lines.append("  (none configured)")
    for w in data["deadline_watches"]:
        ch = w.get("current_cheapest")
        if ch:
            lines.append(f"  {w['route']}: cheapest {ch['price']:.0f}"
                         f" (dep {ch['depart_date']})  must arrive by {w['must_arrive_by']}"
                         f"  max price {w['max_price']}")
        else:
            lines.append(f"  {w['route']}: no fares recorded yet  must arrive by"
                         f" {w['must_arrive_by']}  max price {w['max_price']}")

    lines += ["", "Inspiration shortlist:"]
    insp = data["inspiration"] or {}
    if not any(insp.values()):
        lines.append("  (none)")
    for scope in ("international", "domestic"):
        for i in insp.get(scope, []):
            lines.append(f"  [{scope}] {i['origin']}-{i['destination']}:"
                         f" {i['price']:.0f} (dep {i['depart_date']})")

    n_alerts = conn.execute("SELECT COUNT(*) AS c FROM alerts WHERE ts>=?",
                            (today.isoformat(),)).fetchone()["c"]
    sp = data["spend_this_month"]
    lines += ["",
              f"Alerts today: {n_alerts}",
              f"Duffel spend this month: {sp['searches']} searches (~${sp['est_cost_usd']:.2f})"]
    return "\n".join(lines)
