"""
SwarMind Knowledge Graph Builder

Pipeline:
  raw text → LLM ontology extraction → entity deduplication
           → relation triples → NetworkX graph → community detection
           → agent seed profiles

Improvement over MiroFish:
  - Groq llama-3.3-70b for extraction (faster + cheaper than GPT-4)
  - Community detection with Louvain for agent clustering
  - Relation weights for influence scoring
  - Temporal extraction (when things happened)
"""
from __future__ import annotations
import asyncio
import os

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
import structlog

from .llm import get_llm

log = structlog.get_logger()

# Dimensione dei chunk in parole per l'estrazione del grafo. La KB ha i suoi: vedi memory/knowledge_base.py
CHUNK_SIZE_WORDS = 3000

EXTRACT_SYSTEM = """You are an expert knowledge graph extractor.
Given a text, extract:
1. ENTITIES — people, organizations, places, concepts, events, financial instruments
2. RELATIONS — directed triples (subject, predicate, object)
3. TEMPORAL — time facts (entity, event, date/period)

Return ONLY valid JSON with this schema:
{
  "entities": [
    {"id": "unique_slug", "label": "display name", "type": "PERSON|ORG|PLACE|CONCEPT|EVENT|FINANCIAL", "description": "short desc", "attributes": {}}
  ],
  "relations": [
    {"from": "entity_id", "to": "entity_id", "predicate": "verb phrase", "weight": 0.0-1.0, "sentiment": -1.0-1.0}
  ],
  "temporal": [
    {"entity_id": "id", "event": "what happened", "period": "when"}
  ]
}
Extract as many meaningful entities and relations as possible. Be thorough."""


def select_agent_seeds(
    graph_data: dict,
    max_agents: int = 200,
    eligible_types: tuple[str, ...] = ("PERSON", "ORG"),
    org_percentile_min: float = 40.0,
) -> list[dict]:
    """Select agent seeds from a serialized graph dict (nodes + edges).

    Operates on the dict format produced by KnowledgeGraph.to_dict() and
    persisted via StateStore.save_graph. Builds a minimal nx.DiGraph for
    PageRank scoring, then applies type-based eligibility:
      - PERSON always passes
      - ORG passes only if importance >= org_percentile_min on ORG-only
        PageRank distribution
      - Other types (CONCEPT/PLACE/FINANCIAL/EVENT/UNKNOWN) excluded

    Returns seeds in the same shape spawn_agents expects:
    list of dicts with entity_id, label, type, description, attributes,
    importance, connections.
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    if not nodes:
        return []

    # Build minimal directed graph for PageRank
    g = nx.DiGraph()
    for n in nodes:
        nid = n.get("id")
        if not nid:
            continue
        g.add_node(nid, **{k: v for k, v in n.items() if k != "id"})
    for e in edges:
        src, dst = e.get("from"), e.get("to")
        if src and dst and src in g and dst in g:
            g.add_edge(src, dst, weight=float(e.get("weight", 0.5)))

    if g.number_of_nodes() == 0:
        return []

    try:
        pr = nx.pagerank(g, weight="weight")
    except Exception:
        pr = {n: 1.0 for n in g.nodes}

    # ORG-only percentile threshold
    org_importances = [
        pr[n] for n in g.nodes
        if g.nodes[n].get("type") == "ORG" and n in pr
    ]
    if org_importances:
        sorted_org = sorted(org_importances)
        idx = int(len(sorted_org) * (org_percentile_min / 100.0))
        idx = min(idx, len(sorted_org) - 1)
        org_threshold = sorted_org[idx]
    else:
        org_threshold = 0.0

    ranked = sorted(pr.items(), key=lambda x: x[1], reverse=True)
    eligible: list[tuple[str, float]] = []
    excluded_by_type = 0
    person_kept = 0
    org_kept = 0
    org_dropped = 0
    for node_id, importance in ranked:
        node_type = g.nodes[node_id].get("type", "UNKNOWN")
        if node_type not in eligible_types:
            excluded_by_type += 1
            continue
        if node_type == "ORG" and importance < org_threshold:
            org_dropped += 1
            continue
        if node_type == "PERSON":
            person_kept += 1
        elif node_type == "ORG":
            org_kept += 1
        eligible.append((node_id, importance))
        if len(eligible) >= max_agents:
            break

    log.info(
        "agent_seeds_filtered",
        project_id=graph_data.get("project_id", "unknown"),
        person_kept=person_kept,
        org_kept=org_kept,
        org_dropped=org_dropped,
        excluded_by_type=excluded_by_type,
        org_threshold=round(org_threshold, 6),
        total_eligible=len(eligible),
    )
    if person_kept < 5:
        log.warning(
            "agent_seeds_low_person_count",
            project_id=graph_data.get("project_id", "unknown"),
            person_count=person_kept,
            note="Knowledge base may be poor in human stakeholders",
        )

    seeds = []
    for node_id, importance in eligible:
        node_data = dict(g.nodes[node_id])
        neighbors = list(g.predecessors(node_id)) + list(g.successors(node_id))
        seeds.append({
            "entity_id": node_id,
            "id": node_id,
            "label": node_data.get("label", node_id),
            "type": node_data.get("type", "UNKNOWN"),
            "description": node_data.get("description", ""),
            "attributes": node_data.get("attributes", {}),
            "importance": round(importance, 4),
            "connections": neighbors[:10],
        })
    return seeds


@dataclass
class KnowledgeGraph:
    project_id: str
    graph: nx.DiGraph = field(default_factory=nx.DiGraph)
    communities: dict[str, int] = field(default_factory=dict)
    raw_entities: list[dict] = field(default_factory=list)
    raw_relations: list[dict] = field(default_factory=list)
    temporal_facts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "nodes": [
                {"id": n, **self.graph.nodes[n]} for n in self.graph.nodes
            ],
            "edges": [
                {"from": u, "to": v, **d}
                for u, v, d in self.graph.edges(data=True)
            ],
            "communities": self.communities,
            "temporal_facts": self.temporal_facts,
            "stats": {
                "num_nodes": self.graph.number_of_nodes(),
                "num_edges": self.graph.number_of_edges(),
                "num_communities": len(set(self.communities.values())),
            },
        }

    def get_agent_seeds(
        self,
        max_agents: int = 200,
        eligible_types: tuple[str, ...] = ("PERSON", "ORG"),
        org_percentile_min: float = 40.0,
    ) -> list[dict]:
        """Return top-N entities ranked by centrality as agent seed profiles.

        Filters by entity type to exclude non-agentifiable entities
        (CONCEPT/PLACE/FINANCIAL/EVENT) which would produce narrative
        false positives if rendered as speaking agents. PERSON always
        passes; ORG passes only if importance >= org_percentile_min on
        the ORG-only PageRank distribution.
        """
        if self.graph.number_of_nodes() == 0:
            return []

        # PageRank-based importance scoring
        try:
            pr = nx.pagerank(self.graph, weight="weight")
        except Exception:
            pr = {n: 1.0 for n in self.graph.nodes}

        # ORG-only percentile threshold
        org_importances = [
            pr[n] for n in self.graph.nodes
            if self.graph.nodes[n].get("type") == "ORG" and n in pr
        ]
        if org_importances:
            sorted_org = sorted(org_importances)
            idx = int(len(sorted_org) * (org_percentile_min / 100.0))
            idx = min(idx, len(sorted_org) - 1)
            org_threshold = sorted_org[idx]
        else:
            org_threshold = 0.0

        # Filter by eligibility while preserving ranking
        ranked = sorted(pr.items(), key=lambda x: x[1], reverse=True)
        eligible: list[tuple[str, float]] = []
        excluded_by_type = 0
        person_kept = 0
        org_kept = 0
        org_dropped = 0
        for node_id, importance in ranked:
            node_type = self.graph.nodes[node_id].get("type", "UNKNOWN")
            if node_type not in eligible_types:
                excluded_by_type += 1
                continue
            if node_type == "ORG" and importance < org_threshold:
                org_dropped += 1
                continue
            if node_type == "PERSON":
                person_kept += 1
            elif node_type == "ORG":
                org_kept += 1
            eligible.append((node_id, importance))
            if len(eligible) >= max_agents:
                break

        log.info(
            "agent_seeds_filtered",
            project_id=self.project_id,
            person_kept=person_kept,
            org_kept=org_kept,
            org_dropped=org_dropped,
            excluded_by_type=excluded_by_type,
            org_threshold=round(org_threshold, 6),
        )
        if person_kept < 5:
            log.warning(
                "agent_seeds_low_person_count",
                project_id=self.project_id,
                person_count=person_kept,
                note="Knowledge base may be poor in human stakeholders",
            )

        seeds = []
        for node_id, importance in eligible:
            node_data = dict(self.graph.nodes[node_id])
            neighbors = list(self.graph.predecessors(node_id)) + list(
                self.graph.successors(node_id)
            )
            seeds.append(
                {
                    "entity_id": node_id,
                    "label": node_data.get("label", node_id),
                    "type": node_data.get("type", "UNKNOWN"),
                    "description": node_data.get("description", ""),
                    "attributes": node_data.get("attributes", {}),
                    "importance": round(importance, 4),
                    "community": self.communities.get(node_id, 0),
                    "connections": neighbors[:10],
                    "temporal_facts": [
                        t for t in self.temporal_facts if t["entity_id"] == node_id
                    ],
                }
            )
        return seeds


class GraphBuilder:
    """Extract entities & relations from documents and build a KnowledgeGraph."""

    def __init__(self, llm=None):
        self._llm = llm or get_llm()

    async def build(
        self, project_id: str, text: str, chunk_size: int = CHUNK_SIZE_WORDS, ingest_kb: bool = True
    ) -> KnowledgeGraph:
        """Process a document in chunks and merge into a single graph.

        ingest_kb=False (ricostruzione del grafo) lascia la KB com'e': si ricostruisce allo spawn.
        """
        kg = KnowledgeGraph(project_id=project_id)

        chunks = self._chunk_text(text, chunk_size)
        log.info("graph_build_start", project_id=project_id, chunks=len(chunks))
        # Salva i chunk grezzi nella KB del progetto (per retrieval durante simulazione)
        # In un thread con un tetto di tempo, come ogni chiamata a Chroma dal loop: se non riesce, la KB
        # si ricostruisce allo spawn (_ensure_project_kb)
        if ingest_kb:
            try:
                from ..config import Config
                from ..memory.chroma_client import chroma_settings
                from ..memory.knowledge_base import ProjectKnowledgeBase
                host, port, token = chroma_settings()

                def _ingest():
                    kb = ProjectKnowledgeBase(project_id, host=host, port=port, token=token)
                    kb.ingest_text(text)

                await asyncio.wait_for(asyncio.to_thread(_ingest), Config.CHROMA_KB_INGEST_TIMEOUT)
            except asyncio.TimeoutError:
                log.warning("kb_ingest_failed", project_id=project_id,
                            error=f"timeout after {Config.CHROMA_KB_INGEST_TIMEOUT:g}s")
            except Exception as e:
                log.warning("kb_ingest_failed", project_id=project_id, error=str(e))

        # Extract from each chunk in parallel
        results = await self._llm.batch_complete(
            [
                [
                    {"role": "system", "content": EXTRACT_SYSTEM},
                    {"role": "user", "content": f"Extract from this text:\n\n{chunk}"},
                ]
                for chunk in chunks
            ],
            tier="heavy",
            temperature=0.2,
            max_tokens=16000,
            concurrency=5,
        )

        # Merge results
        all_entities: dict[str, dict] = {}
        all_relations: list[dict] = []
        all_temporal: list[dict] = []

        for raw in results:
            parsed = self._safe_parse(raw)
            if not parsed:
                continue
            for ent in parsed.get("entities", []):
                eid = ent.get("id", "")
                if eid and eid not in all_entities:
                    all_entities[eid] = ent
            all_relations.extend(parsed.get("relations", []))
            all_temporal.extend(parsed.get("temporal", []))

        kg.raw_entities = list(all_entities.values())
        kg.raw_relations = all_relations
        kg.temporal_facts = all_temporal

        # Build NetworkX graph
        for ent in kg.raw_entities:
            kg.graph.add_node(
                ent["id"],
                label=ent.get("label", ent["id"]),
                type=ent.get("type", "UNKNOWN"),
                description=ent.get("description", ""),
                attributes=ent.get("attributes", {}),
            )

        for rel in kg.raw_relations:
            src, dst = rel.get("from"), rel.get("to")
            if src and dst and src in kg.graph and dst in kg.graph:
                kg.graph.add_edge(
                    src,
                    dst,
                    predicate=rel.get("predicate", "relates_to"),
                    weight=float(rel.get("weight", 0.5)),
                    sentiment=float(rel.get("sentiment", 0.0)),
                )

        # Community detection using greedy modularity
        if kg.graph.number_of_nodes() > 0:
            undirected = kg.graph.to_undirected()
            try:
                communities = nx.community.greedy_modularity_communities(undirected)
                for i, community in enumerate(communities):
                    for node in community:
                        kg.communities[node] = i
            except Exception:
                pass  # fallback: all in community 0

        log.info(
            "graph_build_done",
            project_id=project_id,
            nodes=kg.graph.number_of_nodes(),
            edges=kg.graph.number_of_edges(),
            communities=len(set(kg.communities.values())),
        )
        return kg

    @staticmethod
    def _chunk_text(text: str, size: int) -> list[str]:
        """Split text into overlapping chunks."""
        words = text.split()
        overlap = size // 10
        chunks, i = [], 0
        while i < len(words):
            chunk = " ".join(words[i : i + size])
            chunks.append(chunk)
            i += size - overlap
        return chunks or [text]

    @staticmethod
    def _safe_parse(raw: str) -> dict | None:
        """Parse JSON, stripping markdown fences if present."""
        # Rimuovi fence ```json ... ``` con newline
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Cerca il primo blocco JSON valido nel testo
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception:
                    pass
        return None
