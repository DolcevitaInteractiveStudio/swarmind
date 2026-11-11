"""SwarMind population pipeline.

Generazione struttura della popolazione di agenti per simulazione,
separata dalla logica di knowledge graph e dinamica del dibattito.

Componenti:
  - Demographer: brief -> PopulationSpec (distribuzione tipologica)
  - PersonaGenerator: PopulationSpec + contesto KB -> agenti
"""
from .demographer import Demographer, PopulationSpec, Segment

__all__ = ["Demographer", "PopulationSpec", "Segment"]
