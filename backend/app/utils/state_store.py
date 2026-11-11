"""SwarMind State Store — JSON-on-disk persistence for simulation data."""
from __future__ import annotations

import json
import os
from pathlib import Path


class StateStore:
    def __init__(self, base_dir: str):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, project_id: str) -> Path:
        d = self.base / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _sim_dir(self, simulation_id: str) -> Path:
        d = self.base / "sims" / simulation_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_graph(self, project_id: str, data: dict):
        path = self._project_dir(project_id) / "graph.json"
        path.write_text(json.dumps(data, indent=2))

    def load_graph(self, project_id: str) -> dict:
        path = self._project_dir(project_id) / "graph.json"
        if not path.exists():
            raise FileNotFoundError(f"Graph not found for project {project_id}")
        return json.loads(path.read_text())

    # Ricostruzione del grafo: il grafo in uso resta da parte finche' il nuovo non e' salvato
    def set_aside_graph(self, project_id: str) -> bool:
        """Sposta graph.json in graph.previous.json. False se non c'era un grafo."""
        d = self._project_dir(project_id)
        if not (d / "graph.json").exists():
            return False
        os.replace(d / "graph.json", d / "graph.previous.json")
        return True

    def restore_previous_graph(self, project_id: str) -> bool:
        """Rimette in uso il grafo messo da parte. False se non ce n'era uno."""
        d = self._project_dir(project_id)
        if not (d / "graph.previous.json").exists():
            return False
        os.replace(d / "graph.previous.json", d / "graph.json")
        return True

    def drop_previous_graph(self, project_id: str):
        (self._project_dir(project_id) / "graph.previous.json").unlink(missing_ok=True)

    def save_agents(self, simulation_id: str, agents: list[dict]):
        path = self._sim_dir(simulation_id) / "agents.json"
        path.write_text(json.dumps(agents, indent=2))

    def load_agents(self, simulation_id: str) -> list[dict]:
        path = self._sim_dir(simulation_id) / "agents.json"
        if not path.exists():
            return []
        return json.loads(path.read_text())

    def save_simulation(self, simulation_id: str, data: dict):
        path = self._sim_dir(simulation_id) / "simulation.json"
        path.write_text(json.dumps(data, indent=2))

    def load_simulation(self, simulation_id: str) -> dict:
        path = self._sim_dir(simulation_id) / "simulation.json"
        if not path.exists():
            raise FileNotFoundError(f"Simulation data not found: {simulation_id}")
        return json.loads(path.read_text())

    def save_meta(self, simulation_id: str, data: dict):
        """Salva/aggiorna metadati arbitrari della simulazione (merge non distruttivo)."""
        path = self._sim_dir(simulation_id) / "meta.json"
        existing = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text())
            except Exception:
                existing = {}
        existing.update(data)
        path.write_text(json.dumps(existing, indent=2))

    def load_meta(self, simulation_id: str) -> dict:
        """Carica i metadati della simulazione, ritorna {} se assenti."""
        path = self._sim_dir(simulation_id) / "meta.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except Exception:
            return {}

    def save_report(self, simulation_id: str, data: dict):
        path = self._sim_dir(simulation_id) / "report.json"
        path.write_text(json.dumps(data, indent=2))

    def load_report(self, simulation_id: str) -> dict:
        path = self._sim_dir(simulation_id) / "report.json"
        if not path.exists():
            raise FileNotFoundError(f"Report not found: {simulation_id}")
        return json.loads(path.read_text())

    def list_projects(self) -> list[str]:
        return [d.name for d in self.base.iterdir() if d.is_dir() and d.name != "sims"]

    def list_simulations(self) -> list[str]:
        sims_dir = self.base / "sims"
        if not sims_dir.exists():
            return []
        return [d.name for d in sims_dir.iterdir() if d.is_dir()]
