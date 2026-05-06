"""Email alerts via Resend.

Two alert types per spec §10:
  - Daily digest (CRITICAL + HOT clusters; flag NEW HOT)
  - Instant death alert (first time deaths > 0 on a cluster)
"""
from __future__ import annotations

import logging
from datetime import date

import resend

from signalwarn.config import settings
from signalwarn.db import connection

log = logging.getLogger(__name__)

CLASSIFICATION_EMOJI = {
    "CRITICAL": "🔴",
    "HOT": "🟠",
    "WATCH": "🟡",
    "MONITOR": "🟢",
    "NOISE": "⚪",
}


def _send(subject: str, html: str) -> None:
    if not settings.resend_api_key:
        log.warning("RESEND_API_KEY not set; skipping email %r", subject)
        return
    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": settings.alert_from_email,
            "to": [settings.alert_to_email],
            "subject": subject,
            "html": html,
        }
    )


def _format_cluster_line(c: dict) -> str:
    label = f"{c['model_year'] or 'multi-year'} {c['make']} {c['model']}".title()
    return (
        f"{CLASSIFICATION_EMOJI.get(c['classification'], '')} {label} | "
        f"{c['component']} | {c['complaint_count']} complaints | "
        f"Score: {c['score']}"
    )


def send_daily_digest() -> None:
    """Send Jim the morning digest of CRITICAL + HOT clusters."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM clusters
             WHERE classification IN ('CRITICAL', 'HOT')
             ORDER BY score DESC
            """
        )
        rows = cur.fetchall()

    today = date.today().isoformat()
    if not rows:
        body = f"<p>No CRITICAL or HOT clusters today ({today}).</p>"
        _send(f"SIGNAL Daily Brief — {today}", body)
        return

    critical = [r for r in rows if r["classification"] == "CRITICAL"]
    hot = [r for r in rows if r["classification"] == "HOT"]

    body_parts = [f"<h2>SIGNAL Daily Brief — {today}</h2>"]
    if critical:
        body_parts.append(f"<h3>🔴 CRITICAL ({len(critical)})</h3><ul>")
        body_parts.extend(f"<li>{_format_cluster_line(r)}</li>" for r in critical)
        body_parts.append("</ul>")
    if hot:
        body_parts.append(f"<h3>🟠 HOT ({len(hot)})</h3><ul>")
        body_parts.extend(f"<li>{_format_cluster_line(r)}</li>" for r in hot)
        body_parts.append("</ul>")

    _send(f"SIGNAL Daily Brief — {today}", "".join(body_parts))


def send_death_alerts() -> None:
    """Send a one-shot alert for any cluster that just got its first death."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.* FROM clusters c
             WHERE c.death_count > 0
               AND NOT EXISTS (
                 SELECT 1 FROM alerts_sent a
                  WHERE a.cluster_id = c.id AND a.alert_type = 'DEATH'
               )
            """
        )
        new_deaths = cur.fetchall()

        for cluster in new_deaths:
            label = f"{cluster['model_year'] or 'multi-year'} {cluster['make']} {cluster['model']}"
            body = (
                f"<h2>⚠️ SIGNAL DEATH ALERT — {label}</h2>"
                f"<p>A fatality has been reported in an emerging complaint cluster.</p>"
                f"<ul>"
                f"<li>Vehicle: {label}</li>"
                f"<li>Component: {cluster['component']}</li>"
                f"<li>Total Complaints: {cluster['complaint_count']}</li>"
                f"<li>Deaths Reported: {cluster['death_count']}</li>"
                f"<li>Score: {cluster['score']}</li>"
                f"</ul>"
            )
            _send(f"⚠️ SIGNAL DEATH ALERT — {label}", body)
            cur.execute(
                "INSERT INTO alerts_sent (cluster_id, alert_type) VALUES (%s, 'DEATH')",
                (cluster["id"],),
            )
