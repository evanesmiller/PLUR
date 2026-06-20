from __future__ import annotations

import os

_ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_MODEL = "claude-sonnet-4-6"


class PLURAgent:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=_ANTHROPIC_API_KEY)
        return self._client

    def generate_rationale(
        self,
        changes: list[dict],
        risk_before: float,
        risk_after: float,
        venue_name: str,
    ) -> str:
        if not _ANTHROPIC_API_KEY:
            return _placeholder_rationale(changes, risk_before, risk_after)

        changes_text = "\n".join(
            f"  - {c['artist']}: moved from {c['from_stage']} @ {c['from_time']} "
            f"to {c['to_stage']} @ {c['to_time']}"
            for c in changes
        ) or "  (no changes — original schedule was already near-optimal)"

        prompt = f"""You are a crowd-safety expert reviewing a schedule optimization for {venue_name}.

The optimizer made the following artist schedule changes to improve crowd safety:
{changes_text}

Overall risk score improved from {risk_before:.3f} to {risk_after:.3f} (lower is safer, units: integrated excess crowd density).

Write 2–3 paragraphs explaining WHY these specific changes improve safety in terms of:
- Crowd flow patterns and migration between stages
- Avoiding simultaneous high-draw acts that concentrate crowds at adjacent stages
- Reducing egress crush (large acts ending at the same time on nearby stages)

Be specific about the named artists and stages where possible. Write for a festival operations manager.
End with a one-sentence disclaimer that this is a decision-support tool."""

        try:
            msg = self._get_client().messages.create(
                model=_MODEL,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except Exception as e:
            return f"{_placeholder_rationale(changes, risk_before, risk_after)}\n\n[Claude unavailable: {e}]"

    def generate_safety_briefing(
        self,
        venue_name: str,
        risk_windows: list[dict],
        mitigations: dict,
        proposed_schedule: list[dict],
        peak_density: float,
    ) -> str:
        if not _ANTHROPIC_API_KEY:
            return _placeholder_briefing(venue_name, peak_density, mitigations)

        windows_text = "\n".join(
            f"  - Stage {w['stage']}: t={w['t_start']}–{w['t_end']} min, risk score {w['score']:.2f}"
            for w in risk_windows[:5]
        ) or "  No critical risk windows detected."

        n_barriers = len(mitigations.get("barriers", []))
        n_staff = len(mitigations.get("staff", []))

        prompt = f"""You are a crowd-safety expert producing a pre-event safety briefing for {venue_name}.

SIMULATION RESULTS:
- Peak simulated crowd density: {peak_density:.1f} people/m² (danger threshold: 6.0)
- Critical risk windows identified:
{windows_text}

RECOMMENDED MITIGATIONS:
- {n_barriers} barrier placements to redirect crowd flow at chokepoints
- {n_staff} staff deployment positions at high-density zones

Write a structured safety briefing with these sections:
1. Executive Summary (2 sentences)
2. Risk Assessment (key findings from simulation)
3. Recommended Actions (barriers, staff, monitoring)
4. Disclaimer

Include this exact disclaimer at the end:
"PLUR is a planning and decision-support prototype, not a certified life-safety system. All recommendations must be reviewed by qualified event-safety professionals before implementation."

Be concise and professional. Addressed to event operations staff."""

        try:
            msg = self._get_client().messages.create(
                model=_MODEL,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except Exception as e:
            return f"{_placeholder_briefing(venue_name, peak_density, mitigations)}\n\n[Claude unavailable: {e}]"


def _placeholder_rationale(changes: list[dict], risk_before: float, risk_after: float) -> str:
    pct = (risk_before - risk_after) / max(risk_before, 1e-9) * 100
    return (
        f"The optimized schedule reduces integrated crowd-crush risk by {pct:.1f}% "
        f"(score: {risk_before:.3f} → {risk_after:.3f}). "
        f"Key changes separate high-draw acts from adjacent stages and stagger egress times, "
        f"reducing crowd migration spikes between concurrent sets. "
        f"Headliners remain in their designated final slots per event requirements.\n\n"
        f"PLUR is a planning and decision-support prototype, not a certified life-safety system."
    )


def _placeholder_briefing(venue_name: str, peak_density: float, mitigations: dict) -> str:
    n_b = len(mitigations.get("barriers", []))
    n_s = len(mitigations.get("staff", []))
    return (
        f"SAFETY BRIEFING — {venue_name}\n\n"
        f"Executive Summary: Crowd simulation identifies peak density of {peak_density:.1f} people/m². "
        f"Targeted mitigations are recommended.\n\n"
        f"Recommended Actions: Deploy {n_b} crowd-flow barriers at identified chokepoints. "
        f"Position {n_s} staff at high-density zones per the map overlay.\n\n"
        f"PLUR is a planning and decision-support prototype, not a certified life-safety system. "
        f"All recommendations must be reviewed by qualified event-safety professionals before implementation."
    )
