# 6. Templates

[Manual index](README.md) · Previous: [Reading the report](05-reading-the-report.md) · Next: [Admin panel](07-admin-site-landing.md)

A template adapts a simulation to a type of test. It adds three **critical voices**, mandatory
**report sections** and instructions for the report. Without a template ("generic simulation") the
population and up to three critical voices come from the brief alone.

## The five templates

| Template | Use it to test | Mandatory sections (plus *Debate dynamics*) |
|---|---|---|
| `brand_rebranding`: rebranding across generations | A heritage brand repositioning without losing loyal customers | heritage coherence, generational bridge, emotional resonance, narrative vulnerabilities, amplification risks, competitive response |
| `product_launch`: pre-launch feedback and objections | Market reaction to a new product before anyone has tried it | messaging gaps, positioning risks, early adoption signals, competitive response |
| `b2b_saas_pricing`: B2B SaaS pricing test | Business buyers' objections to a price, and negotiation levers | objections analysis, buyer rationalisations, resistance by segment, pricing levers |
| `crisis_comms`: how the public reacts to bad news | A crisis statement before it goes out | narrative vulnerabilities, emotional resonance, amplification risks, trust recovery path |
| `feature_validation`: is it worth building? | Whether users would really adopt a feature over their current workarounds | problem severity, workaround analysis, adoption friction, opportunity cost |

Every template caps critical voices at 15% of the agents and 25% of the posts.

## Structure of a template

Templates are YAML files in `backend/app/templates/simulations/`:

- `<id>.yml`, in English, holds everything: id, name, description, version, `max_adversarial_share`,
  `adversarial_post_share_cap`, the placeholder of the question, recommended entities, three
  `adversarial_personas` (each with a stable `key`, name, role, background, beliefs, fears,
  communication style, conviction and emotional state) and `report_focus` (`mandatory_sections`,
  `extra_instructions`).
- `locales/it/<id>.yml` holds only the translatable fields in Italian (name, description,
  placeholder, recommended entities, extra instructions, and per persona: name, role, background,
  beliefs, fears, motivations), with the calibration for the Italian market. It is merged onto the
  English base; numbers and structure always come from the base.

Inside `extra_instructions`, refer to a persona as `{persona:<key>}`: it is replaced by the
persona's name in the simulation language. A simulation uses the template in its own language; the
interface lists templates in the interface language.

## Editing or adding a template

1. Copy an existing template, give it a new `id` (the file name) and edit it. Keep it generic: no
   real brands, clients or people.
2. Add the Italian overlay in `locales/it/<id>.yml` with the same persona keys.
3. New mandatory sections need a definition in `backend/app/report/sections.py`.
4. Validate:

   ```bash
   docker compose exec backend python -m app.templates.validate
   ```

   It checks required fields, unique persona keys, persona references, and that each overlay
   exists, has the same keys and contains only translatable fields. It prints one `ERROR` line per
   problem and exits with code 1.
5. Restart: `docker compose restart backend worker`.
