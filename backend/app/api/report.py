"""
/api/report

GET  /api/report/<sim_id>            → legge il report generato
POST /api/report/<sim_id>/chat       → chat con il ReportAgent o un agente specifico
GET  /api/report/<sim_id>/export     → esporta report in markdown (piano Pro+)
"""
import re
from xml.sax.saxutils import escape as _xml_escape

from flask import Blueprint, request, jsonify, g, Response, current_app
from app.core import i18n
from app.core.i18n import api_error
from app.models import Simulation, AuditLog
from app.utils.state_store import StateStore
from .auth import login_required, plan_required
from .site import product_name


def _pdf_text(text: str) -> str:
    """Report text as reportlab Paragraph markup: escaped, then only our own **bold** -> <b>.

    The report contains user input (topic, question) and model output: unescaped, a tag such as
    <img src="http://internal/..."> made the backend fetch URLs and read local files (security
    audit 2026-11, PDF export finding).
    """
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _xml_escape(text or ""))

report_bp = Blueprint("report", __name__)


def _store():
    return StateStore(current_app.config["SIMULATIONS_DIR"])


@report_bp.get("/<string:sim_id>")
@login_required
def get_report(sim_id: str):
    Simulation.query.filter_by(
        id=sim_id, user_id=g.current_user.id
    ).first_or_404()

    store = _store()
    try:
        report = store.load_report(sim_id)
    except FileNotFoundError:
        return jsonify({"error": api_error("report_not_ready")}), 404

    return jsonify(report), 200


@report_bp.post("/<string:sim_id>/chat")
@login_required
@plan_required(feature="can_chat_with_agents")
def chat(sim_id: str):
    """Chat interattiva con il ReportAgent o con un singolo agente simulato."""
    Simulation.query.filter_by(
        id=sim_id, user_id=g.current_user.id
    ).first_or_404()

    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    agent_id = data.get("agent_id")  # None = parla con ReportAgent

    if not message:
        return jsonify({"error": api_error("empty_message")}), 400

    store = _store()
    try:
        sim_data = store.load_simulation(sim_id)
        report_data = store.load_report(sim_id)
    except FileNotFoundError:
        return jsonify({"error": api_error("simulation_data_not_found")}), 404

    import asyncio
    from app.core.llm_router import config_for_user, MultiProviderLLM
    from app.population.integration import render_subject_card

    sim_rec = Simulation.query.get(sim_id)
    # The chat answers in the simulation language, like the report
    lang = sim_rec.language
    sim_meta = store.load_meta(sim_id)
    subject_card = sim_meta.get("subject_card") or render_subject_card(sim_meta.get("population_spec"), lang)
    subject_block = f"SUBJECT CARD:\n{subject_card}\n\n" if subject_card else ""
    llm_config = config_for_user(
        g.current_user.id,
        provider=sim_rec.llm_provider,
        credential_id=sim_rec.llm_credential_id,
    )
    llm = MultiProviderLLM(llm_config)

    if agent_id:
        # Trova profilo agente
        agents = store.load_agents(sim_id)
        agent = next((a for a in agents if a["agent_id"] == agent_id), None)
        if not agent:
            return jsonify({"error": api_error("agent_not_found")}), 404

        system = (
            f"{subject_block}"
            f"You are {agent['name']}, {agent['role']}.\n"
            f"Background: {agent.get('background','')}\n"
            f"Current opinion: {agent.get('current_opinion','')}\n"
            f"Emotional state: {agent.get('emotional_state','neutral')}\n"
            "Answer in the first person, staying perfectly in character."
        )
    else:
        system = (
            "You are SwarMind's ReportAgent. You have access to the simulation report "
            "and can answer questions about the results, the agents, the trends that emerged "
            "and the predictions generated.\n\n"
            f"{subject_block}"
            f"REPORT:\n{report_data.get('report_markdown','')[:4000]}"
        )
    # Last instruction of the system prompt: the user's question follows it
    system = i18n.with_directive(system, lang)

    loop = asyncio.new_event_loop()
    try:
        reply = loop.run_until_complete(
            llm.complete(
                [{"role": "system", "content": system},
                 {"role": "user", "content": message}],
                tier="agent",
                temperature=0.7,
                max_tokens=1024,
            )
        )
    finally:
        loop.close()

    return jsonify({"reply": reply, "agent_id": agent_id}), 200


@report_bp.get("/<string:sim_id>/export")
@login_required
@plan_required(feature="can_export_report")
def export_report(sim_id: str):
    sim = Simulation.query.filter_by(
        id=sim_id, user_id=g.current_user.id
    ).first_or_404()

    store = _store()
    try:
        report = store.load_report(sim_id)
    except FileNotFoundError:
        return jsonify({"error": api_error("report_not_available")}), 404

    md = report.get("report_markdown", i18n.t(sim.language, "pdf.report_unavailable"))
    AuditLog.log("report_exported", user_id=g.current_user.id,
                 resource_type="simulation", resource_id=sim_id)

    return Response(
        md,
        mimetype="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=report_{sim_id}.md"},
    )


@report_bp.get("/<string:sim_id>/export/pdf")
@login_required
@plan_required(feature="can_export_report")
def export_report_pdf(sim_id: str):
    sim = Simulation.query.filter_by(
        id=sim_id, user_id=g.current_user.id
    ).first_or_404()
    lang = sim.language
    store = _store()
    try:
        report = store.load_report(sim_id)
    except FileNotFoundError:
        return jsonify({"error": api_error("report_not_available")}), 404

    md = report.get("report_markdown", i18n.t(lang, "pdf.report_unavailable"))
    confidence = report.get("confidence_score", 0)
    # Report recenti: livello qualitativo calcolato dal sistema; i vecchi hanno solo il numero
    confidence_label = report.get("confidence_label")

    # Genera PDF con reportlab
    try:
        from io import BytesIO
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
        from reportlab import rl_config
        # No external resources in the PDF: report content never names images or fonts to load
        rl_config.trustedSchemes = []
        rl_config.trustedHosts = []

        buf = BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4,
                                leftMargin=25*mm, rightMargin=25*mm,
                                topMargin=20*mm, bottomMargin=20*mm)

        DARK    = colors.HexColor("#0D0F14")
        ACCENT  = colors.HexColor("#4F8EF7")
        LIGHT   = colors.HexColor("#F4F6FB")
        BORDER  = colors.HexColor("#E2E8F0")
        GRAY    = colors.HexColor("#6B7280")
        WHITE   = colors.white
        W = A4[0] - 50*mm

        def sp(n=6): return Spacer(1, n)

        styles = {
            "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=18,
                   textColor=WHITE, leading=24),
            "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13,
                   textColor=DARK, leading=18, spaceBefore=14, spaceAfter=4),
            "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=11,
                   textColor=ACCENT, leading=16, spaceBefore=8, spaceAfter=3),
            "body": ParagraphStyle("body", fontName="Helvetica", fontSize=10,
                    textColor=colors.HexColor("#2D3748"), leading=15,
                    spaceAfter=4, alignment=TA_JUSTIFY),
            "li": ParagraphStyle("li", fontName="Helvetica", fontSize=10,
                  textColor=colors.HexColor("#2D3748"), leading=15,
                  spaceAfter=2, leftIndent=12),
            "td": ParagraphStyle("td", fontName="Helvetica", fontSize=9,
                  textColor=DARK, leading=13),
            "th": ParagraphStyle("th", fontName="Helvetica-Bold", fontSize=9,
                  textColor=WHITE, leading=13),
        }

        story = []

        # Header
        conf_pct = confidence_label or (f"{int(confidence*100)}%" if confidence else i18n.t(lang, "pdf.not_available"))
        hdr = Table([[
            Paragraph(i18n.t(lang, "pdf.title", name=_xml_escape(product_name())), ParagraphStyle("ht",
                fontName="Helvetica-Bold", fontSize=16, textColor=WHITE, leading=20)),
            Paragraph(i18n.t(lang, "pdf.confidence", value=conf_pct), ParagraphStyle("hc",
                fontName="Helvetica-Bold", fontSize=11, textColor=ACCENT,
                leading=16, alignment=TA_CENTER)),
        ]], colWidths=[W*0.75, W*0.25])
        hdr.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), DARK),
            ("TOPPADDING", (0,0), (-1,-1), 12),
            ("BOTTOMPADDING", (0,0), (-1,-1), 12),
            ("LEFTPADDING", (0,0), (-1,-1), 12),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LINEBELOW", (0,0), (-1,-1), 2, ACCENT),
        ]))
        story.append(hdr)
        story.append(sp(12))

        # Parse markdown line by line
        lines = md.split("\n")
        i = 0
        table_rows = []
        in_table = False

        while i < len(lines):
            line = lines[i]

            # Table row
            is_tr = line.startswith("|") and line.endswith("|")
            is_sep = is_tr and all(c in "|-: " for c in line)

            if is_tr and not is_sep:
                cells = [c.strip() for c in line.split("|") if c.strip()]
                table_rows.append(cells)
                in_table = True
                i += 1
                continue

            if in_table and not is_tr:
                # Flush table
                if table_rows:
                    col_n = max(len(r) for r in table_rows)
                    col_w = W / col_n
                    t_data = []
                    for ri, row in enumerate(table_rows):
                        style = styles["th"] if ri == 0 else styles["td"]
                        t_data.append([Paragraph(_pdf_text(c), style) for c in (row + [""]*(col_n-len(row)))])
                    tbl = Table(t_data, colWidths=[col_w]*col_n)
                    ts = [
                        ("BACKGROUND", (0,0), (-1,0), DARK),
                        ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LIGHT]),
                        ("GRID", (0,0), (-1,-1), 0.3, BORDER),
                        ("TOPPADDING", (0,0), (-1,-1), 5),
                        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                        ("LEFTPADDING", (0,0), (-1,-1), 6),
                        ("VALIGN", (0,0), (-1,-1), "TOP"),
                    ]
                    tbl.setStyle(TableStyle(ts))
                    story.append(tbl)
                    story.append(sp(8))
                table_rows = []
                in_table = False

            # Headings
            if line.startswith("# "):
                txt = line[2:].strip()
                t = Table([[Paragraph(_pdf_text(txt), styles["h1"])]], colWidths=[W])
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0,0), (-1,-1), DARK),
                    ("TOPPADDING", (0,0), (-1,-1), 10),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 10),
                    ("LEFTPADDING", (0,0), (-1,-1), 12),
                    ("LINEBELOW", (0,0), (-1,-1), 1.5, ACCENT),
                ]))
                story.append(t)
                story.append(sp(8))
            elif line.startswith("## "):
                story.append(Paragraph(_pdf_text(line[3:].strip()), styles["h2"]))
                story.append(HRFlowable(width="100%", thickness=0.3, color=BORDER))
                story.append(sp(4))
            elif line.startswith("### "):
                story.append(Paragraph(_pdf_text(line[4:].strip()), styles["h3"]))
            elif line.startswith("- ") or line.startswith("* "):
                story.append(Paragraph(f"&#8226;  {_pdf_text(line[2:].strip())}", styles["li"]))
            elif line.strip():
                story.append(Paragraph(_pdf_text(line.strip()), styles["body"]))
            else:
                story.append(sp(4))

            i += 1

        # Flush final table
        if table_rows:
            col_n = max(len(r) for r in table_rows)
            col_w = W / col_n
            t_data = []
            for ri, row in enumerate(table_rows):
                style = styles["th"] if ri == 0 else styles["td"]
                t_data.append([Paragraph(_pdf_text(c), style) for c in (row + [""]*(col_n-len(row)))])
            tbl = Table(t_data, colWidths=[col_w]*col_n)
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0,0), (-1,0), DARK),
                ("ROWBACKGROUNDS", (0,1), (-1,-1), [WHITE, LIGHT]),
                ("GRID", (0,0), (-1,-1), 0.3, BORDER),
                ("TOPPADDING", (0,0), (-1,-1), 5),
                ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                ("LEFTPADDING", (0,0), (-1,-1), 6),
                ("VALIGN", (0,0), (-1,-1), "TOP"),
            ]))
            story.append(tbl)

        # Footer
        story.append(sp(16))
        footer = Table([[Paragraph(
            i18n.t(lang, "pdf.footer", sim_id=sim_id, name=_xml_escape(product_name())),
            ParagraphStyle("ft", fontName="Helvetica", fontSize=8,
                           textColor=GRAY, leading=12, alignment=TA_CENTER))
        ]], colWidths=[W])
        footer.setStyle(TableStyle([
            ("LINEABOVE", (0,0), (-1,-1), 0.5, BORDER),
            ("TOPPADDING", (0,0), (-1,-1), 8),
        ]))
        story.append(footer)

        doc.build(story)
        buf.seek(0)

        AuditLog.log("report_exported_pdf", user_id=g.current_user.id,
                     resource_type="simulation", resource_id=sim_id)

        return Response(
            buf.read(),
            mimetype="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=report_{sim_id}.pdf"},
        )

    except Exception:
        # Details only in the server log: the exception text revealed hosts, ports and files
        current_app.logger.exception("pdf_export_failed sim_id=%s", sim_id)
        return jsonify({"error": api_error("pdf_failed", error="")}), 500

