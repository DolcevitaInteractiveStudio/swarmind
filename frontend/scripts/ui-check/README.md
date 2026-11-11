# UI check: screenshots and layout checks

Headless Chrome walks every view of the production build in both themes, both
languages and four viewports (390x844, 768x1024, 1280x920, 1920x1080), with the
API answered by fixtures (`mock.mjs`), so no backend is needed.

For each screen it saves a screenshot and reports:

- horizontal page scroll and elements outside the viewport
- text clipped by overflow without an ellipsis
- touch targets under 44px on phones

With `--interactions` it also checks:

- the drawer opens and closes with Esc, a link or route change, and focus returns
- graph pan by touch and mouse, and the zoom buttons
- modals on phones fill the screen and keep their actions visible
- theme and language switch without a reload and persist after one

Run from `frontend/`:

```sh
npm run build
npx vite preview --port 4173 --strictPort &
npm install --no-save puppeteer-core@24     # not a project dependency
CHROME_PATH="/path/to/chrome" node scripts/ui-check/shoot.mjs ../ui-screenshots --interactions
```

Results go to `<outDir>/<viewport>/<theme>-<lang>/<view>.png`, and problems to
`<outDir>/report.txt`. `npm run check:contrast` covers colour contrast
separately, from the design tokens.

When you add a view, add its route to `STATES` in `shoot.mjs` and any API data
it needs to `mock.mjs`.

## Landing page and branding

`GET /api/site` comes from `site-fixture.json`, which the backend builds from
its own defaults. Regenerate it after changing the default landing copy
(`backend/app/locales/*.yml`, key `landing`) or the settings schema:

```sh
python scripts/ui-check/site_fixture.py      # with the backend's Python environment
```

A state can ask for a variant of the settings with `site:`: `on` (default),
`off` (landing turned off: `/` must end on `/login`), `brand` (product name,
logos from `fixtures/`, favicon and colours that pass AA) and `bad-contrast`
(colours below AA: the theme defaults must stay, with a console warning).
`expect:` checks the path the page ends on, `verify:` runs extra checks on the
page (brand colour, logo, favicon, title).

With `--interactions` the Site & branding flow runs end to end: change the
headline, upload a logo, change both primary colours, open the preview (it must
show the unsaved draft and follow later edits), save (the app shell must take
the new brand at once), then open `/` as a visitor in both themes. Its
screenshots go to `<outDir>/flow/`.
