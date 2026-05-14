# AgentSec Blogs

`agentsec-blogs` is a Codex skill for browsing, filtering, and summarizing recent security research across the AI and agent software stack.

## What It Does

- Searches current sources on the web through Codex
- Focuses on the last 30 days by default
- Filters for AI, agent, MCP, A2A, AGENTS.md, workflow, inference, vector database, training, and related security topics
- Returns structured digest fields:
  - `title`
  - `time`
  - `source`
  - `author`
  - `link`
  - `summary`
  - `keywords`

## Coverage Model

The skill is meant to cover the full AI and agent software ecosystem:

- Top layer: AI agents, browser or coding agents, edge or embodied agents, model application stores, model platforms, and protocol or skill surfaces such as MCP, A2A, ANP, ACP, Skills, and `AGENTS.md`
- Middle layer: agent frameworks, workflow orchestration, reasoning engines, inference engines, deployment layers, model gateways, caching, and tool execution paths
- Bottom layer: vector databases, retrieval systems, fine-tuning, reinforcement learning, training platforms, distributed training, and AI kernel or library components

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
- `Use $agentsec-blogs to map recent incidents by layer: protocols, frameworks, workflow engines, inference, and infrastructure.`

## Repository Layout

- `SKILL.md`: skill instructions and workflow
- `agents/openai.yaml`: display metadata for Codex
- `references/`: curated source lists
- `scripts/`: optional local fallback scripts
