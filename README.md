# news-agent-ai

An AI-powered news monitoring agent built on the [Anthropic Claude](https://www.anthropic.com) SDK.
Given a list of topics, it fetches RSS feeds and HackerNews, clusters articles by theme, scores
relevance, and writes a polished daily Markdown briefing.

## Features

- **Tool-use agentic loop** — Claude drives multi-step research via three tools:
  - `fetch_rss` — parses any RSS/Atom feed with feedparser
  - `search_news` — searches HackerNews Algolia API
  - `write_briefing` — persists the final Markdown file
- **Deduplication** — `RssFetcher` deduplicates articles by URL across all feeds
- **Recency ranking** — items are sorted newest-first before being passed to the model
- **Configurable topics** — any subject matter via CLI or Python API
- **Watch mode** — runs on a schedule, writing dated files to a directory
- **Rich terminal UI** — spinner progress, coloured output, optional preview

## Requirements

- Python 3.11+
- An Anthropic API key (`ANTHROPIC_API_KEY` environment variable)

## Installation

```bash
pip install news-agent-ai
# or for development:
git clone https://github.com/example/news-agent-ai
cd news-agent-ai
pip install -e ".[dev]"
```

## Quick Start

```bash
export ANTHROPIC_API_KEY="sk-ant-..."

# Generate a one-shot briefing
news-agent brief --topics "AI agents, LLM, SAP" --output briefing.md

# Preview the first 60 lines immediately
news-agent brief --topics "AI agents, LLM" --preview

# Add extra RSS feeds
news-agent brief \
  --topics "Kubernetes, Platform Engineering" \
  --feed https://kubernetes.io/feed.xml \
  --feed https://thenewstack.io/feed/ \
  --output k8s-briefing.md

# Run on a schedule (every hour, save to briefings/ directory)
news-agent watch --topics "AI agents, LLM" --interval 3600 --output-dir briefings
```

## Python API

```python
from news_agent import NewsAgent

agent = NewsAgent()  # reads ANTHROPIC_API_KEY from env

result_path = agent.run(
    topics=["AI agents", "SAP", "LLM"],
    output_path="briefing.md",
    extra_feeds=[
        "https://techcrunch.com/feed/",
        "https://hnrss.org/frontpage",
    ],
    verbose=True,   # print tool calls to stdout
)
print(f"Briefing written to: {result_path}")
```

### `RssFetcher` standalone

```python
from news_agent import RssFetcher

fetcher = RssFetcher()
items = fetcher.fetch("https://hnrss.org/frontpage")
for item in items[:5]:
    print(item["title"], "—", item["published"])

# Fetch many feeds, deduplicating across all
all_items = fetcher.fetch_many([
    "https://hnrss.org/frontpage",
    "https://techcrunch.com/feed/",
])
```

## Output Format

The generated Markdown briefing follows this structure:

```markdown
# Daily News Briefing — 2025-06-03

> **Topics**: AI agents, LLM, SAP

---

## Executive Summary
- Key signal 1
- Key signal 2

---

## Topic: AI agents
### Key Signals
- Signal description (relevance: 9/10)

### Top Stories
| Relevance | Title | Source | Published |
|-----------|-------|--------|-----------|
| 9/10 | [Story title](https://...) | HackerNews | 2025-06-03 |

### Analysis
Trend analysis in 2-3 sentences.

---

## Appendix: All Sources
- [Title](URL) — Source, Date
```

## Architecture

```
news_agent/
├── __init__.py       # Public exports: NewsAgent, RssFetcher
├── agent.py          # NewsAgent: Anthropic tool-use agentic loop
├── fetcher.py        # RssFetcher: feedparser wrapper with dedup + ranking
└── cli.py            # Click CLI: `brief` and `watch` commands
```

### Agentic loop

`NewsAgent.run()` implements a standard tool-use loop:

1. Send user message + tool definitions to `claude-sonnet-4-6`
2. On `stop_reason == "tool_use"`, execute every requested tool
3. Append tool results and loop
4. Break when `write_briefing` succeeds or `stop_reason == "end_turn"`
5. Safety ceiling of 20 rounds prevents runaway loops

## Environment Variables

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Required. Your Anthropic API key. |

## Development

```bash
pip install -e ".[dev]"

# Lint
ruff check news_agent/

# Type-check
mypy news_agent/

# Tests
pytest
```

## License

MIT
