"""
SwarMind Celery Tasks

Long-running tasks offloaded from the HTTP request cycle:
  - build_graph_task      : document → knowledge graph
  - spawn_agents_task     : graph → agent pool
  - run_simulation_task   : simulation loop
  - generate_report_task  : report generation
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import structlog
from celery.exceptions import Ignore
from celery.signals import task_failure, worker_ready

from app import celery_app
from app.config import Config
from app.core.graph_builder import GraphBuilder
from app.core.i18n import DEFAULT_LANGUAGE, normalize_language
from app.agents.agent import AgentFactory
from app.simulation import lifecycle
from app.simulation.engine import (
    DEFAULT_ADVERSARIAL_POST_SHARE_CAP,
    SimulationEngine,
    SimulationState,
    SimStatus,
)
from app.report.report_agent import ReportAgent
from app.utils.document_parser import parse_document
from app.utils.state_store import StateStore

log = structlog.get_logger()
cfg = Config()
store = StateStore(cfg.SIMULATIONS_DIR)


def run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    except Exception:
        raise
    finally:
        loop.close()


def _enter_phase(task, simulation_id: str, status: str) -> None:
    """Registra la fase. Una simulazione gia' chiusa non riparte e non fa partire i task collegati."""
    if not lifecycle.enter_phase(simulation_id, status, task.request.id):
        log.info("task_skipped_sim_closed", simulation_id=simulation_id, task=task.name)
        raise Ignore()


def _simulation_language(simulation_id: str, language: str | None) -> str:
    """Lingua della simulazione: quella passata dall'API o, per i task accodati prima della colonna,
    simulations.language dal DB (le righe esistenti valgono "it")."""
    lang = normalize_language(language)
    if lang:
        return lang
    try:
        import psycopg2
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url:
            conn = psycopg2.connect(db_url)
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT language FROM simulations WHERE id=%s", (simulation_id,))
                    row = cur.fetchone()
            finally:
                conn.close()
            lang = normalize_language(row[0]) if row else None
    except Exception as e:
        log.warning("simulation_language_read_failed", simulation_id=simulation_id, error=str(e)[:300])
    if not lang:
        log.warning("simulation_language_default", simulation_id=simulation_id, language=DEFAULT_LANGUAGE)
    return lang or DEFAULT_LANGUAGE


def _post_share_cap(template: dict | None) -> float:
    """Tetto alla quota di post adversarial: quello del template, se valido, o il default."""
    try:
        cap = float((template or {}).get("adversarial_post_share_cap", DEFAULT_ADVERSARIAL_POST_SHARE_CAP))
    except (TypeError, ValueError):
        return DEFAULT_ADVERSARIAL_POST_SHARE_CAP
    return max(0.0, min(1.0, cap))


def _ensure_project_kb(project_id: str, source_path: str | None) -> int:
    """Ritorna i chunk della KB del progetto, ricostruendola dal file sorgente se e' vuota o vecchia.

    Vecchia vuol dire chunk di una versione precedente o embedding diverso da quello di questo
    processo. Solo embedding, nessuna chiamata LLM. Un errore qui non ferma lo spawn: la simulazione
    gira con la KB che c'era o, se non c'era, senza KB e il motore registra kb_empty.
    """
    from app.memory.knowledge_base import KB_CHUNKING_VERSION, ProjectKnowledgeBase

    existing = 0
    try:
        kb = ProjectKnowledgeBase(
            project_id, host=cfg.CHROMA_HOST, port=cfg.CHROMA_PORT, token=cfg.CHROMA_TOKEN
        )
        existing = kb.count()
        old_version = kb.chunking_version()
        old_embedding = kb.embedding_version()
        if existing and kb.is_current():
            return existing
        if not source_path or not os.path.exists(source_path):
            log.warning("kb_source_missing", project_id=project_id, existing_chunks=existing)
            return existing
        text = parse_document(source_path)
        if not text.strip():
            raise lifecycle.LifecycleError("empty_document")
        chunks = kb.ingest_text(text)
        if existing:
            log.info("kb_rebuilt", project_id=project_id, old_version=old_version,
                     new_version=KB_CHUNKING_VERSION, old_embedding=old_embedding,
                     new_embedding=kb.embedding_version(), old_chunks=existing, chunks=chunks)
        else:
            log.info("kb_reingested", project_id=project_id, chunks=chunks, embedding=kb.embedding_version())
        return chunks
    except Exception as e:
        log.warning("kb_reingest_failed", project_id=project_id, error=str(e)[:300])
        return existing


@celery_app.task(bind=True, name="swarmind.build_graph")
def build_graph_task(self, project_id: str, file_path: str, simulation_topic: str, rebuild: bool = False):
    """Parse document and build knowledge graph.

    rebuild=True (POST /api/graph/<id>/rebuild): il grafo in uso e' gia' in graph.previous.json.
    La KB non si tocca (si ricostruisce allo spawn); se la ricostruzione fallisce torna il grafo precedente.
    """
    self.update_state(state="STARTED", meta={"phase": "parsing", "progress": 0})

    try:
        # Parse document
        text = parse_document(file_path)
        log.info("document_parsed", project_id=project_id, chars=len(text))

        self.update_state(state="PROGRESS", meta={"phase": "extracting", "progress": 20})

        # Build graph usando l'LLM configurato a livello progetto
        from app.core.llm import get_llm_for_project
        builder = GraphBuilder(llm=get_llm_for_project(project_id))
        kg = run_async(builder.build(project_id, text, ingest_kb=not rebuild))

        self.update_state(state="PROGRESS", meta={"phase": "clustering", "progress": 80})

        # Save graph
        store.save_graph(project_id, kg.to_dict())
        if rebuild:
            store.drop_previous_graph(project_id)

        # Aggiorna il DB direttamente
        try:
            from app.models.base import db
            from app.models.simulation import Project
            project_obj = Project.query.get(project_id)
            if project_obj:
                project_obj.graph_built = True
                project_obj.graph_error = None
                project_obj.graph_error_detail = None
                project_obj.num_entities = kg.graph.number_of_nodes()
                project_obj.num_relations = kg.graph.number_of_edges()
                db.session.commit()
        except Exception as db_err:
            log.warning("graph_db_update_failed", error=str(db_err))

        self.update_state(state="SUCCESS", meta={"phase": "done", "progress": 100})
        log.info("graph_task_done", project_id=project_id, nodes=kg.graph.number_of_nodes(), rebuild=rebuild)

        return {
            "project_id": project_id,
            "nodes": kg.graph.number_of_nodes(),
            "edges": kg.graph.number_of_edges(),
            "communities": len(set(kg.communities.values())),
        }

    except Exception as e:
        log.error("graph_task_failed", project_id=project_id, error=str(e), rebuild=rebuild)
        _record_graph_failure(project_id, e, rebuild)
        raise


def _record_graph_failure(project_id: str, exc: BaseException, rebuild: bool) -> None:
    """Una ricostruzione fallita rimette in uso il grafo precedente, se c'era; altrimenti come un primo build."""
    if rebuild and store.restore_previous_graph(project_id):
        lifecycle.record_rebuild_failure(project_id, exc)
    else:
        lifecycle.record_failure(lifecycle.PHASE_GRAPH, project_id, exc)


@celery_app.task(bind=True, name="swarmind.spawn_agents")
def spawn_agents_task(
    self,
    simulation_id: str,
    project_id: str,
    simulation_topic: str,
    num_agents: int = 200,
    language: str | None = None,
):
    """Generate agent personas from knowledge graph seeds."""
    _enter_phase(self, simulation_id, "SPAWNING_AGENTS")
    self.update_state(state="STARTED", meta={"phase": "loading_graph", "progress": 0})
    language = _simulation_language(simulation_id, language)

    try:
        # ── REFACTOR persona-pipeline (Step 3) ───────────────
        # Sostituisce il flusso seeds-based con Demographer+PersonaGenerator.
        # Il blocco adversarial sotto resta invariato.
        from app.core.llm import get_llm_for_simulation
        from app.population.demographer import Demographer
        from app.population.persona_generator import PersonaGenerator
        from app.population.integration import (
            read_brief_from_disk,
            extract_domain_context,
            render_subject_card,
            critical_voices_for_spec,
        )
        import psycopg2 as _psycopg2_meta
        import os as _os_meta

        # 1. Carica il brief originale dal DB (source_file_path)
        brief_text = ""
        source_file_path = None
        try:
            db_url = _os_meta.environ.get("DATABASE_URL", "")
            if db_url:
                _conn = _psycopg2_meta.connect(db_url)
                _cur = _conn.cursor()
                _cur.execute(
                    "SELECT source_file_path FROM projects WHERE id=%s",
                    (project_id,),
                )
                _row = _cur.fetchone()
                _cur.close(); _conn.close()
                if _row and _row[0]:
                    source_file_path = _row[0]
                    brief_text = read_brief_from_disk(_row[0])
        except Exception as _brief_err:
            log.warning(
                "brief_read_failed",
                project_id=project_id,
                error=str(_brief_err),
            )
        # La KB si perde se Chroma viene ricreato: va controllata prima di ogni simulazione
        kb_chunks = _ensure_project_kb(project_id, source_file_path)
        try:
            store.save_meta(simulation_id, {"kb_chunks": kb_chunks})
        except Exception as _meta_err:
            log.warning("save_meta_failed", simulation_id=simulation_id, error=str(_meta_err))

        if not brief_text:
            log.error("brief_text_missing", project_id=project_id)
            raise lifecycle.LifecycleError("no_brief")

        # 2. Carica il KG ed estrai contesto di dominio (entita' non-PERSON)
        graph_data = store.load_graph(project_id)
        domain_context = extract_domain_context(graph_data)

        # 3. Demographer: brief -> PopulationSpec
        self.update_state(
            state="PROGRESS",
            meta={"phase": "demographer_running", "progress": 5},
        )
        log.info(
            "demographer_phase_start",
            simulation_id=simulation_id,
            project_id=project_id,
            brief_chars=len(brief_text),
            domain_context_chars=len(domain_context),
            language=language,
        )
        demographer = Demographer(project_id=project_id, tier="heavy")
        pop_spec = run_async(
            demographer.run(brief=brief_text, total_agents=num_agents, language=language)
        )
        subject_card = render_subject_card(pop_spec, language)

        # 4. Persisti PopulationSpec in meta.json (ispezionabile + pronto
        #    per essere citato dal ReportAgent in Step 4)
        try:
            store.save_meta(simulation_id, {
                "population_spec": pop_spec.to_dict(),
                "subject_card": subject_card,
                "language": language,
            })
        except Exception as _meta_err:
            log.warning(
                "save_meta_failed",
                simulation_id=simulation_id,
                error=str(_meta_err),
            )

        # 5. PersonaGenerator: PopulationSpec + domain_context -> agenti
        self.update_state(
            state="PROGRESS",
            meta={"phase": "generating_personas", "progress": 25},
        )
        log.info(
            "persona_generator_phase_start",
            simulation_id=simulation_id,
            segments_count=len(pop_spec.segments),
            total_agents=pop_spec.total_agents,
        )
        persona_gen = PersonaGenerator(
            project_id=project_id,
            simulation_id=simulation_id,
            tier="heavy",
            diversity_temperature=cfg.AGENT_DIVERSITY_TEMPERATURE,
            language=language,
        )
        gen_result = run_async(
            persona_gen.run(spec=pop_spec, domain_context=domain_context)
        )
        agents = gen_result.agents
        log.info(
            "persona_generator_phase_done",
            simulation_id=simulation_id,
            agents_generated=len(agents),
            failures=len(gen_result.failures),
            by_segment=gen_result.by_segment,
        )

        # AgentFactory ancora servita per spawn_adversarial_agents qui sotto
        factory = AgentFactory(llm=get_llm_for_simulation(simulation_id))
        # ────────────────────────────────────────────────────────────

        # ── Spawn agenti avversari da template + custom (se la sim li ha) ──
        try:
            import psycopg2 as _psycopg2
            import os as _os
            import json as _json_mod
            from app.templates import get_registry as _get_tpl_registry

            db_url = _os.environ.get("DATABASE_URL", "")
            adversarial_specs = []
            brief_voices = []
            template_meta = None

            if db_url:
                conn = _psycopg2.connect(db_url)
                cur = conn.cursor()
                cur.execute(
                    "SELECT template_id, custom_adversaries FROM simulations WHERE id=%s",
                    (simulation_id,)
                )
                row = cur.fetchone()
                cur.close(); conn.close()
                if row:
                    template_id, custom_adv = row
                    # 1. Template personas (pre-scritte nel YAML), nella lingua della simulazione
                    if template_id:
                        tpl = _get_tpl_registry().get(template_id, language)
                        if tpl:
                            template_meta = tpl
                            adversarial_specs.extend(tpl.get("adversarial_personas", []))
                    # 2. Custom adversaries (nome+ruolo dall'utente, verranno arricchite via LLM)
                    if custom_adv:
                        # custom_adv puo' arrivare come lista o come stringa JSON
                        if isinstance(custom_adv, str):
                            try:
                                custom_adv = _json_mod.loads(custom_adv)
                            except Exception:
                                custom_adv = []
                        if isinstance(custom_adv, list):
                            adversarial_specs.extend(custom_adv)
                    # 3. Senza template: voci critiche dal brief (nessuna chiamata LLM in piu')
                    if not template_id:
                        brief_voices = critical_voices_for_spec(pop_spec, simulation_id, language=language)

            # ─── Patch: vincolo max_adversarial_share ──────────────────────
            # Limita gli adversari a una frazione del totale agenti per evitare
            # bias di critica strutturale (problema rilevato nei test interni:
            # 24% di volume da agenti anti-X).
            adversarial_truncation_info = None
            import math as _math
            # Default 15%, override nel template via 'max_adversarial_share'
            max_share = 0.15
            if template_meta:
                try:
                    max_share = float(template_meta.get("max_adversarial_share", 0.15))
                except (TypeError, ValueError):
                    max_share = 0.15

            # Il tetto ai post serve al run, che non legge il template
            try:
                store.save_meta(simulation_id, {"adversarial_post_share_cap": _post_share_cap(template_meta)})
            except Exception as _meta_err:
                log.warning("save_meta_failed", simulation_id=simulation_id, error=str(_meta_err))

            if adversarial_specs:
                max_allowed = max(1, _math.floor(num_agents * max_share))
                original_count = len(adversarial_specs)

                if original_count > max_allowed:
                    import random as _random
                    # Seed deterministico per riproducibilita' della stessa sim
                    _random.seed(f"{simulation_id}:adv_truncate")
                    adversarial_specs = _random.sample(adversarial_specs, max_allowed)
                    adversarial_truncation_info = {
                        "original_count": original_count,
                        "kept_count": max_allowed,
                        "max_share": max_share,
                        "num_agents": num_agents,
                        "method": "random_sample",
                    }
                    log.warning(
                        "adversarial_truncated",
                        simulation_id=simulation_id,
                        original=original_count,
                        kept=max_allowed,
                        max_share=max_share,
                        num_agents=num_agents,
                    )
                    # Persiste l'info per il ReportAgent (warning soft nel report)
                    try:
                        store.save_meta(
                            simulation_id,
                            {"adversarial_truncation": adversarial_truncation_info},
                        )
                    except Exception as _meta_err:
                        log.debug("save_truncation_meta_failed", error=str(_meta_err))

            # Le voci dal brief usano solo i posti lasciati dalle custom, che restano come sono.
            # Niente max(1, ...): con meno di 7 agenti una sola voce supererebbe la quota.
            if brief_voices:
                free_slots = max(0, _math.floor(num_agents * max_share) - len(adversarial_specs))
                log.info("critical_voices_selected",
                         simulation_id=simulation_id,
                         proposed=len(brief_voices),
                         kept=min(free_slots, len(brief_voices)),
                         max_share=max_share,
                         num_agents=num_agents)
                adversarial_specs.extend(brief_voices[:free_slots])

            if adversarial_specs:
                log.info("adversarial_spawn_start",
                         simulation_id=simulation_id,
                         count=len(adversarial_specs),
                         template=template_meta["id"] if template_meta else None)
                adv_agents = run_async(
                    factory.spawn_adversarial_agents(
                        adversarial_specs=adversarial_specs,
                        simulation_id=simulation_id,
                        sim_topic=simulation_topic,
                        subject_card=subject_card,
                        language=language,
                    )
                )
                agents.extend(adv_agents)
        except Exception as adv_err:
            log.warning("adversarial_spawn_failed",
                        simulation_id=simulation_id, error=str(adv_err))

        if not agents:
            raise lifecycle.LifecycleError("no_agents")

        from app.agents.stance import stance_counts
        log.info("stance_initial", simulation_id=simulation_id, **stance_counts(agents))

        # Serialize agent data (not the full Agent objects — just profiles)
        agent_profiles = [a.to_dict() for a in agents]
        store.save_agents(simulation_id, agent_profiles)

        self.update_state(state="SUCCESS", meta={"phase": "done", "progress": 100})
        log.info("spawn_task_done", simulation_id=simulation_id, agents=len(agents))

        return {"simulation_id": simulation_id, "num_agents": len(agents)}

    except Exception as e:
        log.error("spawn_task_failed", simulation_id=simulation_id, error=str(e))
        lifecycle.record_failure(lifecycle.PHASE_SPAWN, simulation_id, e)
        raise


@celery_app.task(bind=True, name="swarmind.run_simulation")
def run_simulation_task(
    self,
    simulation_id: str,
    project_id: str,
    simulation_topic: str,
    prediction_requirement: str,
    num_rounds: int = 50,
    platform_type: str = "social_media",
    language: str | None = None,
    **kwargs,
):
    """Run the full simulation loop."""
    # Riconsegnato dopo un riavvio del worker: non si riparte da capo in silenzio
    delivery = self.request.delivery_info or {}
    if lifecycle.abort_redelivered_run(simulation_id, self.request.id, bool(delivery.get("redelivered"))):
        raise Ignore()
    _enter_phase(self, simulation_id, "RUNNING")
    self.update_state(state="STARTED", meta={"phase": "init", "round": 0})
    language = _simulation_language(simulation_id, language)

    try:
        # Load graph and rebuild agent objects
        graph_data = store.load_graph(project_id)
        agent_profiles = store.load_agents(simulation_id)

        from app.agents.agent import Agent, AgentPersona
        from app.core.llm import get_llm_for_simulation as _get_llm_sim
        from app.memory.agent_memory import AgentMemory

        agents = []
        for profile in agent_profiles:
            persona = AgentPersona(
                name=profile["name"],
                role=profile["role"],
                background=profile.get("background") or "",
                personality=profile.get("personality", {}),
                core_beliefs=profile.get("core_beliefs") or [],
                motivations=profile.get("motivations") or [],
                fears=profile.get("fears") or [],
                communication_style=profile.get("communication_style", "casual"),
                initial_opinion=profile.get("current_opinion", ""),
                opinion_strength=profile.get("opinion_strength", 0.5),
                emotional_state=profile.get("emotional_state", "neutral"),
            )
            memory = AgentMemory(
                agent_id=profile["agent_id"],
                simulation_id=simulation_id,
            )
            agent = Agent(
                agent_id=profile["agent_id"],
                entity_id=profile["entity_id"],
                entity_type=profile["entity_type"],
                persona=persona,
                memory=memory,
                simulation_id=simulation_id,
                current_opinion=profile.get("current_opinion", ""),
                opinion_strength=profile.get("opinion_strength", 0.5),
                emotional_state=profile.get("emotional_state", "neutral"),
                _llm=_get_llm_sim(simulation_id),
                is_adversarial=profile.get("is_adversarial", False),
                language=language,
                stance=profile.get("stance"),
                stance_history=list(profile.get("stance_history") or []),
            )
            agents.append(agent)

        from app.population.integration import (
            change_tested,
            render_subject_card,
            subject_homonyms,
        )
        # Le simulazioni create prima della scheda non la hanno in meta.json
        sim_meta = store.load_meta(simulation_id)
        population_spec = sim_meta.get("population_spec")
        subject_card = sim_meta.get("subject_card") or render_subject_card(population_spec, language)
        if not subject_card:
            log.warning("subject_card_missing", simulation_id=simulation_id)

        state = SimulationState(
            simulation_id=simulation_id,
            project_id=project_id,
            topic=simulation_topic,
            total_rounds=num_rounds,
            agents=agents,
            subject_card=subject_card,
            language=language,
            subject_homonyms=subject_homonyms(population_spec),
            change_tested=change_tested(population_spec, prediction_requirement, simulation_topic),
            adversarial_post_share_cap=sim_meta.get(
                "adversarial_post_share_cap", DEFAULT_ADVERSARIAL_POST_SHARE_CAP
            ),
        )

        from app.core.llm import get_llm_for_simulation
        engine = SimulationEngine(
            redis_url=cfg.REDIS_URL,
            llm=get_llm_for_simulation(simulation_id),
        )

        # Progress callback
        async def on_round(sim_state, round_result):
            self.update_state(
                state="PROGRESS",
                meta={
                    "phase": "simulating",
                    "round": round_result.round_num,
                    "total_rounds": sim_state.total_rounds,
                    "entropy": round_result.opinion_entropy,
                },
            )
            if not lifecycle.record_round(simulation_id, round_result.round_num, sim_state.total_posts):
                # Fermata dall'utente: se la revoca del task non e' arrivata, il loop esce qui
                sim_state.status = SimStatus.STOPPED

        final_state = run_async(
            engine.run(
                state,
                platform_type=platform_type,
                entropy_threshold=cfg.OPINION_ENTROPY_THRESHOLD,
                on_round_complete=on_round,
            )
        )

        # Save stato finale degli agenti (posts_made, current_opinion, opinion_strength aggiornati)
        try:
            final_agent_profiles = [a.to_dict() for a in final_state.agents]
            store.save_agents(simulation_id, final_agent_profiles)
            log.info("agents_final_saved", simulation_id=simulation_id, count=len(final_agent_profiles))
        except Exception as save_err:
            log.warning("agents_final_save_failed", error=str(save_err))

        # Save simulation results
        store.save_simulation(simulation_id, {
            "status": final_state.status.value,
            "rounds_completed": final_state.current_round,
            "total_posts": final_state.total_posts,  # intera simulazione, non solo il feed in memoria
            "social_feed": final_state.social_feed[-200:],  # last 200 posts
            "post_engagement": getattr(final_state, "post_engagement", {}),  # Patch H: contatori di TUTTI i post
            "response_stats": getattr(final_state, "response_stats", {}),
            "adversarial_post_share": final_state.adversarial_post_stats(),
            "round_metrics": [
                {
                    "round": r.round_num,
                    "entropy": r.opinion_entropy,
                    "polarization": r.polarization_score,
                    "actions": len(r.actions),
                }
                for r in final_state.rounds
            ],
        })

        # Gli errori dei singoli agenti non interrompono il loop: se nessuno ha risposto non c'e' nulla da analizzare
        stats = final_state.response_stats
        valid_replies = stats["posted"] + stats["engagement"] + stats["do_nothing"]
        failed_replies = sum(stats.values()) - valid_replies
        if failed_replies and not valid_replies:
            raise lifecycle.LifecycleError("no_valid_replies", {"failed": failed_replies})

        # COMPLETED lo scrive il report: fino ad allora la UI continua a seguire la simulazione
        lifecycle.finish_rounds(simulation_id, final_state.current_round, final_state.total_posts)
        self.update_state(state="SUCCESS", meta={"phase": "done"})
        return {
            "simulation_id": simulation_id,
            "rounds_completed": final_state.current_round,
            "total_posts": final_state.total_posts,
        }

    except Exception as e:
        log.error("simulation_task_failed", simulation_id=simulation_id, error=str(e))
        lifecycle.record_failure(lifecycle.PHASE_ROUNDS, simulation_id, e)
        raise


@celery_app.task(bind=True, name="swarmind.generate_report")
def generate_report_task(
    self,
    simulation_id: str,
    prediction_requirement: str,
    language: str | None = None,
    **kwargs,
):
    """Generate the final prediction report."""
    _enter_phase(self, simulation_id, "GENERATING_REPORT")
    self.update_state(state="STARTED", meta={"phase": "loading"})
    language = _simulation_language(simulation_id, language)

    try:
        sim_data = store.load_simulation(simulation_id)
        # Step 4 refactor: carica PopulationSpec persistito da spawn_agents_task
        # per iniettarlo nel ReportAgent (Appendice Metodologica trasparente).
        try:
            sim_meta = store.load_meta(simulation_id) or {}
            population_spec_for_report = sim_meta.get("population_spec")
        except Exception as _meta_err:
            log.warning(
                "load_meta_failed_for_report",
                simulation_id=simulation_id,
                error=str(_meta_err),
            )
            population_spec_for_report = None
        # Reconstruct a lightweight SimulationState for the ReportAgent
        from app.simulation.engine import SimulationState, SimulationRound

        # Carica agenti per popolare state.agents
        try:
            agent_profiles = store.load_agents(simulation_id)
        except Exception:
            agent_profiles = []
        # Il topic non è salvato nel JSON della simulazione: lo prendiamo dal DB
        # (tabella simulations) via psycopg2 diretto, stesso pattern di altri
        # punti del file. Questo evita problemi di Flask app_context nel task
        # Celery e permette al topic_filter di escludere i nomi del prodotto
        # dai topic emergenti.
        topic_from_db = ""
        project_id_from_db = ""
        try:
            import psycopg2, os
            db_url = os.environ.get("DATABASE_URL", "")
            conn = psycopg2.connect(db_url)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT topic, project_id FROM simulations WHERE id = %s",
                    (simulation_id,),
                )
                row = cur.fetchone()
                if row:
                    topic_from_db = row[0] or ""
                    project_id_from_db = str(row[1]) if row[1] else ""
            conn.close()
        except Exception as db_err:
            log.warning("report_topic_fetch_failed", error=str(db_err))
        # Brief del progetto (stesso parser dello spawn): distingue i fatti del brief dalle affermazioni
        # degli agenti negli scenari e nella previsione. Senza brief quel controllo viene saltato.
        brief_text = ""
        brief_project = sim_data.get("project_id") or project_id_from_db
        try:
            from app.population.integration import read_brief_from_disk
            if brief_project and os.environ.get("DATABASE_URL"):
                import psycopg2
                conn = psycopg2.connect(os.environ["DATABASE_URL"])
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT source_file_path FROM projects WHERE id=%s", (brief_project,))
                        row = cur.fetchone()
                finally:
                    conn.close()
                if row and row[0]:
                    brief_text = read_brief_from_disk(row[0])
        except Exception as brief_err:
            log.warning("report_brief_read_failed", simulation_id=simulation_id, error=str(brief_err)[:300])
        state = SimulationState(
            simulation_id=simulation_id,
            project_id=sim_data.get("project_id") or project_id_from_db,
            topic=sim_data.get("topic") or topic_from_db,
            current_round=sim_data.get("rounds_completed", 0),
            social_feed=sim_data.get("social_feed", []),
            agents=agent_profiles,
            language=language,
        )
        # I totali del report vengono dai contatori dell'intero run: il feed salvato ha solo gli ultimi 200 post
        state.response_stats.update(sim_data.get("response_stats") or {})

        for m in sim_data.get("round_metrics", []):
            state.rounds.append(
                SimulationRound(
                    round_num=m["round"],
                    opinion_entropy=m["entropy"],
                    polarization_score=m["polarization"],
                )
            )

        self.update_state(state="PROGRESS", meta={"phase": "analyzing"})

        from app.core.llm import get_llm_for_simulation
        report_agent = ReportAgent(
            max_tool_calls=cfg.REPORT_AGENT_MAX_TOOL_CALLS,
            max_reflection_rounds=cfg.REPORT_AGENT_MAX_REFLECTION_ROUNDS,
            temperature=cfg.REPORT_AGENT_TEMPERATURE,
            llm=get_llm_for_simulation(simulation_id),
        )
        result = run_async(report_agent.generate(
            state,
            prediction_requirement,
            population_spec=population_spec_for_report,
            adversarial_post_stats=sim_data.get("adversarial_post_share"),
            language=language,
            brief_text=brief_text,
        ))

        store.save_report(simulation_id, {
            "report_markdown": result.report_markdown,
            "key_findings": result.key_findings,
            "confidence_score": result.confidence_score,
            # Livello calcolato dal campione e dalla stabilita' (report/postprocess.assess_confidence)
            "confidence_label": result.confidence_label,
            "confidence_level": result.confidence_basis.get("level"),
            "confidence_basis": result.confidence_basis,
            "scenario_probabilities": result.scenario_probabilities,
            "tool_calls_made": result.tool_calls_made,
            "generated_at": time.time(),
        })

        lifecycle.mark_completed(simulation_id)
        self.update_state(state="SUCCESS", meta={"phase": "done"})
        return {"simulation_id": simulation_id, "confidence": result.confidence_score}

    except Exception as e:
        log.error("report_task_failed", simulation_id=simulation_id, error=str(e))
        lifecycle.record_failure(lifecycle.PHASE_REPORT, simulation_id, e)
        raise


_TASK_PHASES = {
    build_graph_task.name: lifecycle.PHASE_GRAPH,
    spawn_agents_task.name: lifecycle.PHASE_SPAWN,
    run_simulation_task.name: lifecycle.PHASE_ROUNDS,
    generate_report_task.name: lifecycle.PHASE_REPORT,
}


@task_failure.connect
def _record_task_failure(sender=None, exception=None, args=None, kwargs=None, **_):
    """Copre quello che non passa dagli except dei task, come il processo ucciso (WorkerLostError)."""
    phase = _TASK_PHASES.get(getattr(sender, "name", None))
    if phase == lifecycle.PHASE_GRAPH and args and (kwargs or {}).get("rebuild"):
        _record_graph_failure(args[0], exception, rebuild=True)
    elif phase and args:
        lifecycle.record_failure(phase, args[0], exception)


@celery_app.task(bind=True, name="swarmind.reap_stale_simulations")
def reap_stale_simulations_task(self):
    """Chiude le simulazioni rimaste "in corso" senza un task vivo."""
    def busy_ids():
        return lifecycle.busy_resource_ids(self.app)

    def graph_exists(project_id: str) -> bool:
        try:
            return bool(store.load_graph(project_id))
        except FileNotFoundError:
            # Ricostruzione interrotta: torna il grafo precedente e il progetto resta utilizzabile
            if store.restore_previous_graph(project_id):
                log.warning("graph_rebuild_restored_after_stale", project_id=project_id)
                return True
            return False

    reaped = lifecycle.reap_stale(busy_ids, cfg.STALE_SIMULATION_MINUTES, graph_exists)
    if reaped is None:
        log.warning("stale_reap_skipped", reason="cannot tell which tasks are alive")
        return {"skipped": True}
    log.info("stale_reap_done", **reaped)
    return reaped


@celery_app.task(name=lifecycle.MEMORY_CLEANUP_TASK, ignore_result=True)
def delete_simulation_memory_task(simulation_id: str):
    """Cancella la collection di memoria di una simulazione chiusa. Accodato da lifecycle e dallo stop."""
    from app.memory.memory_cleanup import delete_if_closed
    return delete_if_closed(simulation_id)


@celery_app.task(name="swarmind.sweep_memory_collections", ignore_result=True)
def sweep_memory_collections_task():
    """Riprende le cancellazioni di memoria non riuscite: collection di simulazioni gia' chiuse."""
    from app.memory.memory_cleanup import sweep_closed_memory_collections
    try:
        result = sweep_closed_memory_collections()
    except Exception as e:
        log.warning("memory_sweep_failed", error=str(e)[:300])
        return {"failed": True}
    return {"deleted": len(result["deleted"]), "kept": result["kept"], "orphans": result["orphans"],
            "failed": result["failed"]}


# Dopo la prima passata del reaper (60 s), che puo' chiudere altre simulazioni
MEMORY_SWEEP_DELAY_SECONDS = 180


@worker_ready.connect
def _schedule_memory_sweep(**_):
    try:
        sweep_memory_collections_task.apply_async(countdown=MEMORY_SWEEP_DELAY_SECONDS)
    except Exception as e:
        log.warning("memory_sweep_schedule_failed", error=str(e)[:300])


@worker_ready.connect
def _schedule_stale_reap(**_):
    """Un riavvio perde i task in corso. La seconda passata chiude le righe ancora troppo recenti per la prima."""
    delay = cfg.STALE_SIMULATION_MINUTES * 60 + 60
    try:
        for countdown in (60, delay):
            reap_stale_simulations_task.apply_async(countdown=countdown)
    except Exception as e:
        log.warning("stale_reap_schedule_failed", error=str(e)[:300])
