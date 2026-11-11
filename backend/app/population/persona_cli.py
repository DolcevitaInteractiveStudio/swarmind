"""CLI standalone per testare il PersonaGenerator in isolamento.

Usage:
    python -m app.population.persona_cli <population_spec.json> [opts]

Esempi:
    # Test su una PopulationSpec (fixture di fantasia)
    python -m app.population.persona_cli \\
        tests/fixtures/population_specs/quillfern_pricing.json \\
        --project-id <project_id>

    # Salva agenti generati in output JSON
    python -m app.population.persona_cli \\
        tests/fixtures/population_specs/quillfern_pricing.json \\
        --project-id <project_id> \\
        --out /tmp/quillfern_agents.json

    # Con context di dominio esplicito
    python -m app.population.persona_cli \\
        tests/fixtures/population_specs/quillfern_pricing.json \\
        --project-id <project_id> \\
        --domain-context "Abbonamenti a box di te' sfuso - Concorrenti a 11 e 14 euro al mese."

Output:
    - stdout: lista compatta degli agenti (name, role, segment, opinion)
    - stderr: log + statistiche per segmento
    - --out (opzionale): JSON serializzato degli agenti per ispezione
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .demographer import PopulationSpec
from .persona_generator import PersonaGenerator


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Test the PersonaGenerator on a PopulationSpec (Step 2 standalone).",
    )
    p.add_argument(
        "spec_path",
        type=Path,
        help="Path al file PopulationSpec JSON (output dello Step 1)",
    )
    p.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="Project UUID per recuperare credenziali/modello LLM dal DB",
    )
    p.add_argument(
        "--tier",
        type=str,
        default="heavy",
        choices=["heavy", "agent", "fast"],
        help=(
            "LLM tier (default: heavy). Personas con constraint hard "
            "richiedono modello forte: tier 'agent' produce JSON malformato "
            "e personas che ignorano i constraint del segmento."
        ),
    )
    p.add_argument(
        "--temperature",
        type=float,
        default=1.1,
        help="Diversity temperature (default: 1.1, alta per variare personas)",
    )
    p.add_argument(
        "--domain-context",
        type=str,
        default="",
        help="Testo opzionale di contesto di dominio (Step 3 lo prendera' dal KG)",
    )
    p.add_argument(
        "--language",
        type=str,
        default=None,
        choices=["en", "it"],
        help="Lingua delle personas (default: quella dei segmenti della spec)",
    )
    p.add_argument(
        "--simulation-id",
        type=str,
        default="step2-standalone",
        help="Simulation ID per AgentMemory (default: step2-standalone)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Path opzionale per salvare gli agenti generati come JSON",
    )
    return p.parse_args()


def _agent_to_dict(agent) -> dict:
    """Serializza Agent (escludendo memory e _llm che non sono JSON-friendly)."""
    return {
        "agent_id": agent.agent_id,
        "entity_id": agent.entity_id,
        "entity_type": agent.entity_type,
        "simulation_id": agent.simulation_id,
        "persona": asdict(agent.persona),
        "current_opinion": agent.current_opinion,
        "opinion_strength": agent.opinion_strength,
        "emotional_state": agent.emotional_state,
        "is_adversarial": agent.is_adversarial,
    }


async def _run(args: argparse.Namespace) -> int:
    if not args.spec_path.exists():
        print(f"ERROR: spec file not found: {args.spec_path}", file=sys.stderr)
        return 2

    raw = args.spec_path.read_text(encoding="utf-8")
    spec_dict = json.loads(raw)
    spec = PopulationSpec.from_dict(spec_dict)

    project_id_str = args.project_id or "(system default)"
    print(
        f"# PersonaGenerator test\n"
        f"# spec: {args.spec_path} ({len(spec.segments)} segments, "
        f"{spec.total_agents} agents)\n"
        f"# tier: {args.tier} | temperature: {args.temperature}\n"
        f"# project_id: {project_id_str}\n"
        f"# domain_context: {len(args.domain_context)} chars\n",
        file=sys.stderr,
    )

    generator = PersonaGenerator(
        tier=args.tier,
        project_id=args.project_id,
        simulation_id=args.simulation_id,
        diversity_temperature=args.temperature,
        language=args.language,
    )
    result = await generator.run(spec=spec, domain_context=args.domain_context)

    # Stampa compatta su stdout
    print(f"\n=== AGENTS GENERATED ({result.total}) ===\n")
    for a in result.agents:
        seg = a.entity_id.split(":", 1)[1] if ":" in a.entity_id else a.entity_id
        opinion_short = (a.current_opinion or "")[:80]
        print(
            f"  [{a.agent_id}] {a.persona.name:30} | {seg:35} | "
            f"strength={a.opinion_strength:.2f} | {opinion_short}"
        )

    # Statistiche per segmento (vs spec atteso)
    print(f"\n=== DISTRIBUTION CHECK ===\n")
    actual = result.by_segment
    for s in spec.segments:
        got = actual.get(s.segment_id, 0)
        marker = "OK" if got == s.count else "!!"
        print(f"  [{marker}] {s.segment_id:35} expected={s.count:3} got={got:3}")

    if result.failures:
        print(f"\n=== FAILURES ({len(result.failures)}) ===\n", file=sys.stderr)
        for f in result.failures:
            print(f"  segment={f['segment_id']}  reason={f['reason']}", file=sys.stderr)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        out_data = {
            "spec_source": str(args.spec_path),
            "agents_count": result.total,
            "failures_count": len(result.failures),
            "by_segment": result.by_segment,
            "agents": [_agent_to_dict(a) for a in result.agents],
            "failures": result.failures,
        }
        args.out.write_text(
            json.dumps(out_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"\n# saved to: {args.out}", file=sys.stderr)

    return 0 if not result.failures else 1


def main() -> None:
    args = parse_args()
    rc = asyncio.run(_run(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
