"""Terminal summary: per-corridor cheapest, inspiration shortlist, alerts, spend."""
from . import dashboard, spend


def build_report(conn, cfg, today):
    lines = [f"fare-watch — base {cfg.get('current_base')} — {today.isoformat()}", ""]

    lines.append("Corridors:")
    for c in cfg.get("corridors", []) or []:
        route = f"{c['origin']}-{c['destination']}"
        ch = dashboard.cheapest_for_route(conn, c["origin"], c["destination"])
        threshold = c.get("alert_threshold") or c.get("max_price")
        if ch:
            lines.append(f"  {route}: cheapest {ch['price']:.0f} {c.get('currency', '')}"
                         f" (dep {ch['depart_date']})  threshold {threshold}")
        else:
            lines.append(f"  {route}: no fares recorded yet  threshold {threshold}")

    lines += ["", "Inspiration shortlist:"]
    top_n = (cfg.get("inspiration", {}) or {}).get("top_n_to_verify", 10)
    shortlist = dashboard.inspiration_shortlist(conn, top_n)
    if not shortlist:
        lines.append("  (none)")
    for i in shortlist:
        lines.append(f"  {i['origin']}-{i['destination']}: {i['price']:.0f} (dep {i['depart_date']})")

    n_alerts = conn.execute("SELECT COUNT(*) AS c FROM alerts WHERE ts>=?",
                            (today.isoformat(),)).fetchone()["c"]
    sp = spend.spend_this_month(conn, "duffel", today.strftime("%Y-%m"))
    lines += ["",
              f"Alerts today: {n_alerts}",
              f"Duffel spend this month: {sp['searches']} searches (~${sp['est_cost_usd']:.2f})"]
    return "\n".join(lines)
