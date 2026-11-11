"""Pending report items: wrong consensus thresholds, collective enthusiasm with few enthusiastic agents, list
counts after a removed item, the recommendations limitation without recommendations, the feed counter.

Fictional reports and simulations only. SQLite, no network.
Usage: cd backend && python -m pytest tests/test_report_pending_items.py
"""
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

import pytest

from app.report import postprocess


# ── Consensus thresholds in the confidence text ──────────────────────────────

@pytest.mark.parametrize("sentence", [
    "Il livello di confidenza è Media: il consenso sulla posizione è medio, dal 75%, e lo spostamento è moderato.",
    "La confidenza è bassa perché il consenso medio, che parte dal 75%, non basta.",
    "Con un consenso medio dal 75% la stabilità resta media.",
    "Medium consensus (from 75%) keeps the confidence medium.",
])
def test_wrong_threshold_next_to_the_level_is_removed(sentence):
    out, found = postprocess.fix_consensus_thresholds(f"## Confidenza\n\n{sentence} Il campione è piccolo.", "it")
    assert sentence not in out and "Il campione è piccolo." in out
    assert found and found[0]["level"] == "medium"


@pytest.mark.parametrize("sentence", [
    "Il consenso è alto (dal 75%).",
    "Consenso medio: dal 50% al 75% degli agenti naturali.",
    "Il consenso è medio (66,7% favorevole).",
    "Medium consensus at 66.7% of the natural agents.",
])
def test_right_threshold_or_measured_value_stays(sentence):
    out, found = postprocess.fix_consensus_thresholds(f"## Confidenza\n\n{sentence}", "it")
    assert sentence in out and found == []


# ── Enthusiasm ───────────────────────────────────────────────────────────────

ENTHUSIASM_REPORT = """## Scenari

### Scenario 1: Adozione entusiasta (plausibile)
Gli early adopter mostrano un entusiasmo diffuso per la prova gratuita. Il prezzo resta il nodo.

## Appendice Metodologica

- Prompt entusiasti o pessimisti possono orientare le dinamiche: adozione entusiasta non verificata.
"""


def test_enthusiasm_claims_with_one_enthusiastic_agent_out_of_17():
    out, found = postprocess.fix_enthusiasm_claims(ENTHUSIASM_REPORT, enthusiastic=1, natural=17)
    assert "### Scenario 1: Adozione (plausibile)" in out
    assert "entusiasmo diffuso" not in out and "Il prezzo resta il nodo." in out
    assert "adozione entusiasta non verificata" in out          # the appendix is left alone
    assert {f["action"] for f in found} == {"qualifier_removed", "removed"}


def test_enthusiasm_claims_stay_when_enough_agents_are_enthusiastic():
    out, found = postprocess.fix_enthusiasm_claims(ENTHUSIASM_REPORT, enthusiastic=6, natural=17)
    assert out == ENTHUSIASM_REPORT and found == []


def test_enthusiastic_adoption_in_english():
    out, _ = postprocess.fix_enthusiasm_claims("Enthusiastic adoption is unlikely. Widespread enthusiasm is absent.",
                                               enthusiastic=0, natural=12)
    assert out.strip() == "Adoption is unlikely."


# ── List counts ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("md, expected", [
    ("Emergono tre rischi principali:\n\n- Prezzo\n- Fiducia\n", "Emergono due rischi principali:"),
    ("**Tre rischi:**\n- Prezzo\n  dettaglio\n- Fiducia\n", "**Due rischi:**"),
    ("### 3 obiezioni\n\n1. Prezzo\n2. Tempi\n", "### 2 obiezioni"),
    ("Two risks stand out:\n- Price\n- Trust\n- Timing\n", "Three risks stand out:"),
])
def test_list_count_matches_the_items_left(md, expected):
    out, found = postprocess.fix_list_counts(md)
    assert out.split("\n")[0] == expected and len(found) == 1


@pytest.mark.parametrize("md", [
    "Emergono due rischi:\n- Prezzo\n- Fiducia\n",                 # already right
    "Due rischi pesano sul lancio. Il prezzo e la fiducia.\n",      # no list announced
    "Tre agenti su 17 scrivono:\n- Prezzo\n- Fiducia\n",            # not a list noun
    "Emergono tre rischi:\n- Prezzo\n",                             # one item: the noun would change too
])
def test_list_count_left_alone(md):
    out, found = postprocess.fix_list_counts(md)
    assert out == md and found == []


# ── Recommendations limitation ───────────────────────────────────────────────

LIMIT = "- Le raccomandazioni operative sono coerenti con lo stato del prodotto dichiarato nel topic."


def test_limitation_dropped_for_a_launch_report_without_recommendations():
    md = f"## Gap nel Messaggio di Lancio\n\nTesto.\n\n## Appendice Metodologica\n\n{LIMIT}\n"
    out, dropped = postprocess.drop_recommendations_limit(md)
    assert LIMIT not in out and dropped == 1


@pytest.mark.parametrize("heading", ["## Leve di Negoziazione", "## Raccomandazioni"])
def test_limitation_kept_with_recommendations(heading):
    md = f"{heading}\n\nTesto.\n\n## Appendice Metodologica\n\n{LIMIT}\n"
    out, dropped = postprocess.drop_recommendations_limit(md)
    assert LIMIT in out and dropped == 0


# ── Feed counter ─────────────────────────────────────────────────────────────

@pytest.fixture()
def app(tmp_path):
    from app import create_app
    from app.config import Config
    from app.models import Plan, Project, Simulation, Subscription, User, db
    from app.models.plan import PlanTier
    from app.models.user import Role

    class TestConfig(Config):
        TESTING = True
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'test.db'}"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        UPLOADS_DIR = str(tmp_path / "uploads")
        SIMULATIONS_DIR = str(tmp_path / "sims")
        SECRET_KEY = "test-secret"

    application = create_app(TestConfig)
    with application.app_context():
        user = User(email="user@example.com", role=Role.USER, is_active=True)
        user.set_password("pw-123456")
        db.session.add(user)
        db.session.add(Subscription(user=user, plan=Plan.query.filter_by(tier=PlanTier.PRO).one()))
        db.session.flush()
        db.session.add(Project(id="p1", user_id=user.id, name="P", source_filename="b.txt",
                               source_file_path="/none", graph_built=True))
        db.session.add(Simulation(id="s1", project_id="p1", user_id=user.id, topic="t", prediction_requirement="q",
                                  total_posts=1234))
        db.session.commit()
    return application


def test_feed_serves_the_latest_posts_and_the_real_total(app):
    from app.api.auth import _make_token
    from app.models import User
    from app.utils.state_store import StateStore
    feed = [{"post_id": f"p{i}", "content": f"post {i}"} for i in range(500)]
    StateStore(app.config["SIMULATIONS_DIR"]).save_simulation("s1", {"social_feed": feed})
    with app.app_context():
        tok = _make_token(User.query.filter_by(email="user@example.com").one().id)
    client = app.test_client()
    data = client.get("/api/simulation/s1/feed?per_page=100", headers={"Authorization": f"Bearer {tok}"}).get_json()
    assert data["feed"][0]["post_id"] == "p499" and len(data["feed"]) == 100
    assert data["total"] == 500 and data["total_posts"] == 1234
    asc = client.get("/api/simulation/s1/feed?order=asc&per_page=2", headers={"Authorization": f"Bearer {tok}"})
    assert [p["post_id"] for p in asc.get_json()["feed"]] == ["p0", "p1"]
