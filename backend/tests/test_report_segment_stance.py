"""Stance shares per segment: a sentence is checked against the segment it names, also when segment names share
words ("bike owners" / "bike shop owners"); a removed sentence leaves no empty bullet or blank line in a list.

Fictional segments and figures. No network, no database.
Usage: cd backend && python -m pytest tests/test_report_segment_stance.py
"""
import os

os.environ.setdefault("ENCRYPTION_KEY", "Zm9yLXRlc3RzLW9ubHktbm90LWEtcmVhbC1rZXktMDA=")

from app.report.postprocess import fix_segment_stance_shares
from app.report.stance_metrics import compute_stance_metrics


def _agents(segment_id: str, stances: list[str]) -> list[dict]:
    return [{"agent_id": f"{segment_id}{i}", "entity_id": f"segment:{segment_id}", "is_adversarial": False,
             "stance_history": [{"round": 0, "stance": s}]} for i, s in enumerate(stances)]


def _stance(segments: list[dict], stances: dict[str, list[str]]) -> dict:
    agents = [a for seg_id, values in stances.items() for a in _agents(seg_id, values)]
    return compute_stance_metrics(agents, segments)


PRODUCTION = [
    {"segment_id": "riders", "label": "Current Halden bike owners"},
    {"segment_id": "shops", "label": "Partner bike shop owners and mechanics"},
]
# riders: 80% oppose / 20% support; shops: 25% oppose / 75% support
PRODUCTION_STANCES = {"riders": ["oppose"] * 4 + ["support"], "shops": ["oppose"] + ["support"] * 3}

SHORT = [
    {"segment_id": "owners", "label": "Bike owners"},
    {"segment_id": "shop", "label": "Bike shop owners"},
]
# owners: 60% oppose / 40% neutral; shop: 75% support / 25% neutral
SHORT_STANCES = {"owners": ["oppose"] * 3 + ["neutral"] * 2, "shop": ["support"] * 3 + ["neutral"]}


def test_the_production_sentence_stays_with_its_own_segment():
    stance = _stance(PRODUCTION, PRODUCTION_STANCES)
    md = ("## Opinion Landscape\n\n"
          "- Current Halden bike owners: 80.0% oppose and 20.0% support.\n"
          "- Partner bike shop owners and mechanics: 25.0% oppose and 75.0% support.\n")
    out, found = fix_segment_stance_shares(md, stance, PRODUCTION, "en")
    assert found == [] and out == md


def test_segments_sharing_words_are_told_apart():
    stance = _stance(SHORT, SHORT_STANCES)
    md = ("Stance by segment:\n\n"
          "- Bike owners: 60.0% oppose.\n"
          "- Bike shop owners: 75.0% support.\n"
          "- Among bike shop owners, 25.0% are neutral.\n"
          "- Bike owners (40.0% neutral) and bike shop owners (75.0% support) disagree.\n")
    out, found = fix_segment_stance_shares(md, stance, SHORT, "en")
    assert found == [] and out == md


def test_a_wrong_figure_is_removed_for_the_segment_it_names():
    stance = _stance(SHORT, SHORT_STANCES)
    # 75% support belongs to the shop owners, not to the bike owners
    md = "Stance by segment:\n\n- Bike owners: 75.0% support.\n- Bike shop owners: 75.0% support.\n"
    out, found = fix_segment_stance_shares(md, stance, SHORT, "en")
    assert [(f["segment"], f["action"]) for f in found] == [("Bike owners", "sentence_removed")]
    assert out == "Stance by segment:\n\n- Bike shop owners: 75.0% support.\n"


def test_a_removed_bullet_leaves_no_empty_line_inside_the_list():
    stance = _stance(PRODUCTION, PRODUCTION_STANCES)
    md = ("## Opinion Landscape\n\n"
          "- Partner bike shop owners and mechanics: 25.0% oppose and 75.0% support.\n"
          "- Current Halden bike owners: 55.0% support.\n"
          "- The rest of the agents are neutral.\n\nNext paragraph.\n")
    out, found = fix_segment_stance_shares(md, stance, PRODUCTION, "en")
    assert [f["segment"] for f in found] == ["Current Halden bike owners"]
    assert out == ("## Opinion Landscape\n\n"
                   "- Partner bike shop owners and mechanics: 25.0% oppose and 75.0% support.\n"
                   "- The rest of the agents are neutral.\n\nNext paragraph.\n")
    assert "\n- \n" not in out and "\n-\n" not in out


def test_italian_segments_sharing_words():
    segments = [{"segment_id": "prop", "label": "Proprietari di bici"},
                {"segment_id": "neg", "label": "Proprietari di negozi di bici"}]
    stance = _stance(segments, {"prop": ["oppose"] * 3 + ["support"], "neg": ["support"] * 3 + ["neutral"]})
    md = ("- Proprietari di bici: 75,0% contrari.\n"
          "- Proprietari di negozi di bici: 75,0% a favore.\n"
          "- Proprietari di bici: 75,0% a favore.\n")
    out, found = fix_segment_stance_shares(md, stance, segments, "it")
    assert [f["segment"] for f in found] == ["Proprietari di bici"]
    assert out == "- Proprietari di bici: 75,0% contrari.\n- Proprietari di negozi di bici: 75,0% a favore.\n"


def test_a_generic_segment_word_without_a_name_still_removes_the_figure():
    stance = _stance(SHORT, SHORT_STANCES)
    md = "- One segment is at 33.3% support.\n- Natural agents: 33.3% support.\n"
    out, found = fix_segment_stance_shares(md, stance, SHORT, "en")
    assert [f["action"] for f in found] == ["sentence_removed"]
    assert out == "- Natural agents: 33.3% support.\n"
