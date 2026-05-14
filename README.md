# AgentSec Blogs

`agentsec-blogs` is a Codex skill for browsing, filtering, and summarizing recent AI and agent security blogs from curated security sources.

## What It Does

- Searches current sources on the web through Codex
- Focuses on the last 30 days by default
- Filters for AI, agent, LLM, MCP, RAG, copilot, prompt injection, and related security topics
- Returns structured digest fields:
  - `title`
  - `time`
  - `source`
  - `author`
  - `link`
  - `summary`
  - `keywords`

## Install

Use Codex `skill-installer` from GitHub:

```bash
python3 ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo xinyi-hou/agentsec-blogs \
  --path . \
  --name agentsec-blogs
```

After installation, restart Codex.

## Usage

Example prompts:

- `Use $agentsec-blogs to summarize recent AI security blogs from the last 30 days.`
- `Use $agentsec-blogs to find recent agent security research and return title, source, link, summary, and keywords.`
- `Use $agentsec-blogs to expand the current source list with more AI security blogs.`

## Repository Layout

- `SKILL.md`: skill instructions and workflow
- `agents/openai.yaml`: display metadata for Codex
- `references/`: curated source lists
- `scripts/`: optional local fallback scripts
