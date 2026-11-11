# 7. Admin panel, site & branding, landing page

[Manual index](README.md) · Previous: [Templates](06-templates.md) · Next: [Operations](08-operations.md)

Open the **Admin panel** from the sidebar (admins and superadmins only).

## Dashboard, users, simulations, audit log

- **Dashboard**: users, simulations this month, running simulations, plan distribution.
- **Users**: search, create, change role and plan, suspend and reactivate. A superadmin can also
  delete a user and **sign in as** a user (a temporary one-hour session) to see what they see.
- **Plans** (superadmin): limits and features of each plan, see [chapter 2](02-first-admin-and-providers.md#plans-and-quotas).
- **Simulations**: every simulation of every user, with status and errors.
- **Audit log**: sign-ins, user and plan changes, impersonations, site changes, CLI actions such as
  `create-superadmin`. For site changes only the changed fields are logged, not their values.

## Site & branding (superadmin)

**Admin panel → Site & branding** controls how the app looks and the optional public landing page.
Changes are validated by the server, saved with a revision number (two admins cannot overwrite each
other's changes silently) and recorded in the audit log.

### Branding

- **Product name**, shown in the sidebar, the browser tab and the landing.
- **Logos** for the dark and the light theme, and a **favicon**. Uploaded images are checked and
  re-encoded by the server; size limits are shown next to each field.
- **Colours**: primary and accent for each theme. The editor warns when a colour does not reach
  WCAG AA contrast.

### Landing page

The landing page is **off** by default: visitors to `/` see the sign-in page. When it is on, `/`
shows the landing to visitors who are not signed in.

Content is edited separately for English and Italian:

- **Hero**: title, subtitle, optional image, primary and secondary call to action.
- **Sections**, each can be disabled or reordered: value, how it works, use cases, deliverables,
  open source (repository link, documentation link, license, install snippet), contact.
- **Footer**: company name (empty shows the product name), contact email, privacy and terms URLs.
- **SEO**: page title, description, social image.

The default copy describes SwarMind as a stress test for narratives. The contact section and the
footer address start from `CONTACT_EMAIL` in `.env`; without it the contact section starts disabled.
Use **Preview** to see unsaved changes, then **Save**. Review every link and address before turning
the landing on: it is public.

Links accept `https://`, `http://`, `mailto:`, site paths (`/login`) and anchors (`#contact`) only.
