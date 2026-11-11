# 2. First admin, users and LLM providers

[Manual index](README.md) · Previous: [Installation](01-installation.md) · Next: [Projects and briefs](03-projects-and-briefs.md)

## Create the superadmin

Public sign-up is disabled: every account is created by an administrator. The first one comes from
the command line:

```bash
docker compose exec backend flask --app run create-superadmin --email you@example.com --name "Your Name"
```

The password is asked twice and never echoed (at least 8 characters). For scripted installs, put
it in an environment variable and pass its name:

```bash
docker compose exec -e ADMIN_PASSWORD='…' backend \
  flask --app run create-superadmin --email you@example.com --password-env ADMIN_PASSWORD
```

The superadmin gets the Enterprise plan. Forgot the password? Run the same command with
`--reset-password`. Each run is recorded in the audit log.

## Roles

| Role | Can do |
|---|---|
| user | Projects, simulations, reports, own AI connections |
| admin | Plus the admin panel: users (create, edit, suspend), simulations of everyone, audit log |
| superadmin | Plus plans, deleting users, signing in as a user (impersonation), Site & branding |

## Add users

**Admin panel → Users → New user**: email, initial password, plan and role. Tell the person to change
the password from their profile.

## Plans and quotas

Three plans are created on the first start. A superadmin can edit them (**Admin panel → Plans**):

| | Free | Pro | Enterprise |
|---|---|---|---|
| Simulations per month | 1 | 20 | unlimited |
| Agents per simulation | 50 | 500 | 2000 |
| Rounds per simulation | 20 | 200 | 500 |
| Projects | 3 | 20 | unlimited |
| File size | 5 MB | 50 MB | 500 MB |
| Own API keys | no | yes | yes |
| PDF export, agent chat | no | yes | yes |

Quotas always apply, whether or not billing pages are shown. On a self-hosted install for one team,
give users the Pro or Enterprise plan, or edit the Free plan. **A Free user cannot add API keys**:
without a system key (`GROQ_API_KEY`) such a user cannot run simulations.

There is no payment integration. `BILLING_ENABLED=true` in `.env` shows users the Pricing and
Billing pages and the "Upgrade plan" links; with the default `false` the app never talks about
payments and plans are managed only by admins.

## Connect an LLM provider

Each user connects their own accounts in **AI connections**:

1. Choose a provider: **OpenRouter** (many models with one key), **Groq**, **OpenAI** or **Anthropic**.
2. Paste the API key and select **Connect**; **Test connection** checks it with the provider.
3. The key is encrypted with `ENCRYPTION_KEY` (Fernet: AES-128 with an HMAC-SHA256 signature) before
   it is stored, and is never written to logs.

Models are chosen later:

- per **project**, the *heavy* model: knowledge graph, population of personas, report. Use a strong
  model (for example `anthropic/claude-sonnet-4.5` through OpenRouter);
- per **simulation**, the *agent* model (writes the personas) and the *fast* model (every post of
  every round, by far the most calls). A fast, inexpensive model with good writing in the
  simulation language works well, for example `google/gemini-2.5-flash` through OpenRouter.

Everything you upload and every simulated post is sent to the provider you choose, under its terms
and prices. Check both before uploading confidential briefs.

### System key (optional)

`GROQ_API_KEY` in `.env` is used for any user who has not connected a key of their own, with the
models in `GROQ_MODEL_HEAVY`, `GROQ_MODEL_AGENT` and `GROQ_MODEL_FAST`. Leave it empty if every user
must bring their own key. Then "System default (Groq)" is not offered, and a user without a
connection sees a prompt to open **AI connections**: projects and simulations cannot be created
until a key is connected.
