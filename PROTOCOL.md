# Xammis Live Reports Publishing Protocol

This repository is the public delivery surface for visual reports created by the Xammis Pi agent cast. GitHub Pages publishes the `main` branch root at:

```text
https://xammis.github.io/live-reports/
```

## Canonical folder rule

Every report belongs to exactly one agent and must be committed beneath that agent's lowercase folder:

```text
<agent>/<report-slug>.html
```

Examples:

```text
marla/campaign-performance.html
bond/infrastructure-review.html
coppola/platform-architecture.html
```

The authoritative agent slugs are listed in `agents.json`. A report must never be published at the repository root. Existing root-level historical URLs may remain only as redirects to their canonical agent path.

## Required delivery sequence

1. Generate a complete, self-contained HTML document.
2. Remove credentials, tokens, private keys, sensitive personal data, private callback URLs, and unnecessary local filesystem paths. This repository and its GitHub Pages site are public.
3. Publish with `scripts/publish-report.py`, passing the authoritative authoring agent slug, title, and concise summary.
4. The publisher writes `<agent>/<slug>.html`, updates `reports.json`, regenerates the root and per-agent indexes, commits, and pushes `main`.
5. The publisher waits until GitHub Pages serves the exact current HTML.
6. Only after successful verification may the agent tell the user the report is ready.
7. The user-facing response must contain the public HTTPS URL. A local path, attachment, repository blob URL, or promise that deployment will finish later is not an acceptable delivery.

## Command

```bash
/home/nick/dev/xammis/live-reports/scripts/publish-report.py \
  ~/.agent/diagrams/report-title.html \
  --agent marla \
  --title "Report Title" \
  --summary "One-sentence description"
```

Successful output is JSON containing the verified `url`, repository `path`, and Git commit.

## Repository invariants

- `main` is the publishing branch.
- GitHub Pages serves `/` from the `main` branch.
- `agents.json` is the authoritative folder roster.
- `reports.json` is the authoritative report catalog.
- Each agent folder has an `index.html` generated from `reports.json`.
- Publishing is serialized with a local file lock and uses fast-forward/rebase-safe Git operations.
- The publisher refuses an unexpected Git remote, wrong branch, dirty checkout, malformed HTML, symlink source/destination, unknown agent, or common credential signature.
- Report slugs use lowercase ASCII letters, numbers, and hyphens.
- Updating an existing agent/slug replaces that report and refreshes its publication timestamp.
