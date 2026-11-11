"""CLI standalone per testare il Demographer in isolamento.

Usage:
    python -m app.population.cli <brief_path> [--agents N] [--out PATH]

Esempi:
    python -m app.population.cli tests/fixtures/briefs/quillfern_pricing.txt
    python -m app.population.cli tests/fixtures/briefs/quillfern_pricing.txt --agents 50
    python -m app.population.cli tests/fixtures/briefs/quillfern_pricing.txt \\
        --out /tmp/quillfern_spec.json

Output:
    - Stampa la PopulationSpec come JSON formattato su stdout
    - Se --out specificato, scrive anche su file (utile per diff tra run)

Nessuna integrazione col resto della pipeline: solo Demographer + LLM.
I fixture in tests/fixtures/ sono di fantasia (azienda inventata).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ..utils.document_parser import read_text_file
from .demographer import Demographer


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Test the Demographer on a brief file (Step 1 standalone)."
    )
    p.add_argument(
        "brief_path",
        type=Path,
        help="Path al file di brief (testo grezzo)",
    )
    p.add_argument(
        "--agents",
        type=int,
        default=30,
        help="Numero di agenti target (default: 30)",
    )
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Path opzionale dove scrivere la PopulationSpec come JSON",
    )
    p.add_argument(
        "--tier",
        type=str,
        default="heavy",
        choices=["heavy", "agent", "fast"],
        help="LLM tier (default: heavy)",
    )
    p.add_argument(
        "--temperature",
        type=float,
        default=0.4,
        help="Temperatura LLM (default: 0.4)",
    )
    p.add_argument(
        "--language",
        type=str,
        default=None,
        choices=["en", "it"],
        help="Lingua dei testi della spec (default: quella del brief)",
    )
    p.add_argument(
        "--project-id",
        type=str,
        default=None,
        help=(
            "Project UUID per recuperare credenziali/modello LLM dal DB "
            "(es. 8a427ef6-8a7...). Se omesso, usa il client Groq di "
            "sistema (Llama 3.3 70b)."
        ),
    )
    return p.parse_args()


async def _run(args: argparse.Namespace) -> int:
    if not args.brief_path.exists():
        print(f"ERROR: brief file not found: {args.brief_path}", file=sys.stderr)
        return 2

    # Brief files often come from Word/Outlook in CP1252 (Western European
    # Windows encoding), not UTF-8. read_text_file logs the encoding it used.
    brief = read_text_file(args.brief_path)
    project_id_str = args.project_id or "(system default)"
    print(
        f"# Demographer test\n"
        f"# brief: {args.brief_path} ({len(brief)} chars)\n"
        f"# agents: {args.agents}\n"
        f"# tier: {args.tier} | temperature: {args.temperature}\n"
        f"# language: {args.language or 'brief'}\n"
        f"# project_id: {project_id_str}\n",
        file=sys.stderr,
    )

    demographer = Demographer(tier=args.tier, project_id=args.project_id)
    spec = await demographer.run(
        brief=brief,
        total_agents=args.agents,
        temperature=args.temperature,
        language=args.language,
    )

    spec_dict = spec.to_dict()
    output_json = json.dumps(spec_dict, indent=2, ensure_ascii=False)
    print(output_json)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output_json + "\n", encoding="utf-8")
        print(f"# saved to: {args.out}", file=sys.stderr)

    problems = spec.validate()
    if problems:
        print(f"\n# VALIDATION WARNINGS ({len(problems)}):", file=sys.stderr)
        for p in problems:
            print(f"#   - {p}", file=sys.stderr)
        return 1

    return 0


def main() -> None:
    args = parse_args()
    rc = asyncio.run(_run(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
