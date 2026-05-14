---
name: agentsec-blogs
description: Use Codex web browsing to find, verify, filter, and summarize recent security blogs and advisories across the AI and agent stack. Use when the user asks for an interactive AI or agent security digest, a source-backed watchlist, or a layer-by-layer roundup covering protocols, frameworks, workflows, inference, and infrastructure.
---

# AgentSec Blogs

## Overview

Use this skill when the task should run as a pure Codex workflow. The primary execution path is:
- use Codex web search and page opening to inspect real sources
- decide relevance inside Codex, not via a separate API key
- summarize only after verifying the underlying article page or source page

Default behavior:
- Last 7 days only
- AI / agent security topics only
- Output article records with `title`, `time`, `source`, `author`, `link`, `summary`, and `keywords`
- No extra OpenAI or Packy API key is required

## Coverage Model

Treat the target space as a layered AI and agent ecosystem:
- Top layer:
  - AI agents
  - coding agents
  - browser or desktop agents
  - edge or embodied agents
  - model application stores
  - model platforms
  - protocol and skill surfaces such as MCP, A2A, ANP, ACP, Skills, and `AGENTS.md`
- Middle layer:
  - agent development frameworks
  - workflow orchestration frameworks
  - reasoning engines
  - inference engines
  - inference deployment
  - model gateways
  - LLM caches
  - tool routing and execution paths
- Bottom layer:
  - vector databases
  - retrieval systems
  - fine-tuning
  - reinforcement learning
  - training platforms
  - distributed training
  - AI kernel and runtime libraries

If the user asks for a roundup or analysis, prefer grouping findings by these layers when it improves readability.

## Workflow

1. Load source hints from:
   - `references/default-sources.csv`
   - `references/source-catalog.md`
2. Rank sources using the CTI tier model:
   - Tier 1: authoritative advisories and databases
   - Tier 2: vendor research blogs
   - Tier 3: security news and community
   - Tier 4: OSINT, PoC, and specialist sources
3. Start with Tier 1 and Tier 2 sources, then expand only if the result set is thin.
4. Use Codex web search to locate recent posts from those sources and prefer:
   - source homepage or blog index pages
   - source feeds when exposed in search results
   - direct article URLs from the source domain
5. Open the actual post or source page before including an item. Do not rely on search snippets alone for summaries.
6. Filter semantically for AI or agent relevance. Do not depend on exact keyword matches only.
7. If `summary`, `author`, or `time` is missing from search snippets, open the post page and extract it from the page itself.
8. Produce a digest in Markdown unless the user explicitly asks for JSON or a file.

## Relevance Rules

Treat an item as relevant when it is materially about any of:
- AI, LLM, GenAI, model security, jailbreaks, prompt injection, indirect prompt injection
- AI agents, coding agents, browser agents, tool use, memory, planning, reasoning, autonomous workflows
- MCP, Model Context Protocol, A2A, ANP, ACP, `AGENTS.md`, agent skills, agent frameworks, orchestration layers, workflow engines
- inference engines, model serving, model gateways, LLM caches, reasoning runtimes
- RAG, embeddings, vector databases, vector stores, retrieval systems for AI apps
- fine-tuning, reinforcement learning, training platforms, distributed training, AI runtime or kernel libraries
- vulnerabilities, incidents, exploits, detections, benchmarks, or research affecting the AI or agent stack

Also include adjacent infrastructure topics when the AI or agent angle is clear, for example:
- agent runtime security
- model gateways
- tool execution sandboxes
- data exfiltration through copilots
- memory poisoning
- prompt injection in enterprise SaaS copilots
- vector store abuse
- workflow supply chain compromise
- configuration-driven code execution
- browser extension hijack against AI agents
- control-plane flaws in inference or model platforms

Representative in-scope examples include:
- `Semantic Kernel` and `CrewAI` framework vulnerabilities
- `TrustFall`, `Claude Code MCP Token Theft`, and MCP by-design execution disputes
- `ClaudeBleed` and other browser agent confused deputy issues
- `Gemini CLI` and `GitHub Actions` agentic workflow incidents
- `LiteLLM`, `LeRobot`, and similar inference or infrastructure flaws

Exclude:
- generic cybersecurity news with no meaningful AI or agent angle
- pure product marketing
- reposts when the original article is available
- WeChat public accounts or公众号 mirrors

## Collection Rules

- Keep primary sources separate from secondary summaries.
- Prefer original research, advisories, and vendor blogs over reposts or mirror sites.
- Prefer direct source links over aggregators.
- Keep entries without a usable direct link as manual-review candidates.
- Merge duplicates by canonical source and article URL.
- If the result set is small, broaden the search terms before broadening the source quality bar.

## Output Format

Default digest fields:
- `title`
- `time`
- `source`
- `author`
- `link`
- `summary`
- `keywords`

Use a compact flat list or table. Keep `summary` to one short paragraph or one sentence.

## Search Guidance

Prefer query shapes like:
- `site:vendor.com/blog agent security`
- `site:vendor.com/blog prompt injection`
- `site:vendor.com/blog copilot OR agentic OR mcp`
- `site:vendor.com/blog semantic kernel OR crewai security`
- `site:vendor.com/blog litellm OR model gateway security`
- `site:vendor.com/blog vector database OR inference engine security`
- `site:vendor.com/blog github actions OR coding agent security`
- `site:vendor.com/blog "last 7 days"`
- `site:source-domain recent ai security blog`

If the first pass is sparse, expand with concept terms such as:
- `agent workflow`
- `agent framework`
- `agent protocol`
- `agent skill`
- `reasoning engine`
- `inference engine`
- `model serving`
- `vector database`
- `rag security`
- `tool calling`
- `copilot security`
- `model gateway`
- `agent memory`
- `fine-tuning security`
- `distributed training security`
- `agent2agent`
- `agents.md`

## Interaction Pattern

When the user asks for a digest:
1. Use the curated source list first.
2. Browse current pages and verify dates.
3. Return the most relevant items from the last 7 days.
4. Mention exact dates when useful.
5. Include source links.
6. If the user is reasoning about the software stack, group the results by top layer, middle layer, and bottom layer.

When the user asks to refresh or expand the source list:
1. Compare candidate sources against `references/default-sources.csv`.
2. Keep authoritative and research-heavy sources first.
3. Note which new sources are worth adding and why.

When the user asks for exportable or automated local collection:
1. Explain that this skill is optimized for interactive Codex browsing.
2. Use the bundled scripts only as an explicit fallback for local batch execution.

## Optional Local Fallback

Only if the user explicitly asks for local automation or a shell command, the bundled scripts remain available:
- `scripts/collect_security_blogs.py`
- `scripts/run_blog_collection.sh`

Do not require extra API keys for the normal interactive skill workflow.

## Resources

- `references/source-catalog.md`
- `references/default-sources.csv`
- `scripts/collect_security_blogs.py`
- `scripts/run_blog_collection.sh`
