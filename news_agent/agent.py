"""
NewsAgent — orchestrates RSS fetching, topic clustering, relevance scoring,
and daily briefing generation using the Anthropic SDK with tool use.
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import anthropic

from .fetcher import RssFetcher

# ---------------------------------------------------------------------------
# Tool implementations (called by the agent loop)
# ---------------------------------------------------------------------------

_fetcher = RssFetcher()


def _fetch_rss(url: str) -> str:
    """Fetch and parse an RSS/Atom feed, returning deduplicated recent items."""
    items = _fetcher.fetch(url)
    if not items:
        return json.dumps({"error": f"No items found in feed: {url}"})
    # Return the 20 most-recent items as compact JSON the model can reason over
    return json.dumps({"feed_url": url, "item_count": len(items), "items": items[:20]}, default=str)


def _search_news(query: str) -> str:
    """Search HackerNews Algolia API for recent stories matching the query."""
    try:
        resp = httpx.get(
            "https://hn.algolia.com/api/v1/search_by_date",
            params={"query": query, "tags": "story", "hitsPerPage": 15},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        hits = [
            {
                "title": h.get("title", ""),
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "points": h.get("points", 0),
                "num_comments": h.get("num_comments", 0),
                "created_at": h.get("created_at", ""),
                "author": h.get("author", ""),
            }
            for h in data.get("hits", [])
        ]
        return json.dumps({"query": query, "result_count": len(hits), "results": hits})
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc), "query": query})


def _write_briefing(path: str, content: str) -> str:
    """Write the briefing Markdown to a file, creating parent directories."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return json.dumps({"status": "ok", "path": str(out.resolve()), "bytes": len(content.encode())})


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "name": "fetch_rss",
        "description": (
            "Fetch and parse an RSS or Atom feed URL. "
            "Returns the most-recent items with title, URL, published date, and summary. "
            "Use this for curated news feeds (Reuters, TechCrunch, Hacker News RSS, etc.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Full URL of the RSS or Atom feed.",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "search_news",
        "description": (
            "Search HackerNews for recent stories matching a query. "
            "Returns story title, URL, points, comment count, and publication date. "
            "Use this to discover community reactions to technology topics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms, e.g. 'LLM agents' or 'SAP S/4HANA'.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "write_briefing",
        "description": (
            "Write the final Markdown briefing to a file on disk. "
            "Call this exactly once at the end, after all research is complete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Destination file path, e.g. 'briefing.md'.",
                },
                "content": {
                    "type": "string",
                    "description": "Full Markdown text of the daily briefing.",
                },
            },
            "required": ["path", "content"],
        },
    },
]

# Default RSS feeds to include even when not topic-matched
DEFAULT_FEEDS = [
    "https://feeds.feedburner.com/oreilly/radar/atom",  # O'Reilly Radar
    "https://hnrss.org/frontpage",                     # HN front page RSS
]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class NewsAgent:
    """
    AI news agent that:
    1. Fetches from configurable RSS feeds + HackerNews
    2. Clusters articles by topic
    3. Scores relevance
    4. Generates a daily Markdown briefing
    """

    MODEL = "claude-sonnet-4-6"
    MAX_TOKENS = 8192
    MAX_TOOL_ROUNDS = 20  # safety ceiling for the agentic loop

    def __init__(self, api_key: str | None = None) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)  # falls back to ANTHROPIC_API_KEY env var

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        topics: list[str],
        output_path: str = "briefing.md",
        extra_feeds: list[str] | None = None,
        verbose: bool = False,
    ) -> str:
        """
        Conduct a full news-research cycle and write the briefing.

        Returns the absolute path to the written file.
        """
        feeds = DEFAULT_FEEDS + (extra_feeds or [])
        system_prompt = self._build_system_prompt(topics, feeds, output_path)
        user_message = self._build_user_message(topics, output_path)

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": user_message}
        ]

        result_path: str | None = None
        rounds = 0

        while rounds < self.MAX_TOOL_ROUNDS:
            rounds += 1
            response = self._client.messages.create(
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            )

            if verbose:
                self._print_response_summary(response, rounds)

            # Append assistant turn
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                # Model finished without calling write_briefing — unusual but handle gracefully
                break

            if response.stop_reason != "tool_use":
                break

            # Execute all tool calls and collect results
            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_output = self._dispatch_tool(block.name, block.input, verbose)

                # Check if briefing was written
                if block.name == "write_briefing":
                    try:
                        parsed = json.loads(tool_output)
                        if parsed.get("status") == "ok":
                            result_path = parsed["path"]
                    except (json.JSONDecodeError, KeyError):
                        pass

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": tool_output,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

            # If the briefing was successfully written, we're done
            if result_path:
                break

        if result_path is None:
            # Fallback — agent did not call write_briefing; create a minimal file
            result_path = str(Path(output_path).resolve())
            _write_briefing(output_path, "# News Briefing\n\n*Agent did not produce output.*\n")

        return result_path

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_system_prompt(self, topics: list[str], feeds: list[str], output_path: str) -> str:
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        topic_list = ", ".join(f'"{t}"' for t in topics)
        feed_list = "\n".join(f"  - {f}" for f in feeds)
        return textwrap.dedent(f"""
            You are a senior news analyst AI. Today is {today}.

            Your task is to research the following topics and produce a concise,
            well-structured daily news briefing in Markdown format.

            TOPICS TO COVER: {topic_list}

            RESEARCH PROCESS:
            1. Use `fetch_rss` to retrieve articles from the provided feeds.
            2. Use `search_news` to search HackerNews for each topic.
            3. After gathering sufficient information (aim for 10-30 unique articles
               per topic), cluster articles by theme, score their relevance (1-10),
               and identify key signals or trends.
            4. Call `write_briefing` exactly once with the complete Markdown document
               saved to "{output_path}".

            BRIEFING STRUCTURE (use this Markdown template):
            ```
            # Daily News Briefing — {{date}}

            > **Topics**: {{comma-separated topics}}

            ---

            ## Executive Summary
            2-4 bullet points covering the most important cross-topic signals.

            ---

            ## Topic: {{topic name}}
            ### Key Signals
            - Brief signal description (relevance: N/10)

            ### Top Stories
            | Relevance | Title | Source | Published |
            |-----------|-------|--------|-----------|
            | N/10 | [Title](URL) | Source | Date |

            ### Analysis
            2-3 sentences on trends and implications.

            ---
            (repeat for each topic)

            ## Appendix: All Sources
            - [Title](URL) — Source, Date
            ```

            AVAILABLE RSS FEEDS TO START WITH:
            {feed_list}

            RULES:
            - Be concise. Executive summary ≤ 4 bullets.
            - Relevance scores: 10 = directly on-topic, breaking news;
              5 = moderately related; 1 = tangential mention.
            - Include at least 3 stories per topic when available.
            - Deduplicate: if the same story appears in multiple feeds, list it once.
            - Do NOT fabricate stories. Only include real items from tool results.
            - Write in professional, neutral editorial style.
        """).strip()

    def _build_user_message(self, topics: list[str], output_path: str) -> str:
        today = datetime.now(tz=timezone.utc).strftime("%A, %B %d, %Y")
        topic_str = ", ".join(topics)
        return (
            f"Please research and produce the daily news briefing for {today}.\n"
            f"Topics: {topic_str}\n"
            f"Save the briefing to: {output_path}\n\n"
            "Start by fetching the default feeds, then search HackerNews for each topic."
        )

    def _dispatch_tool(self, name: str, tool_input: dict[str, Any], verbose: bool) -> str:
        if verbose:
            print(f"  [tool] {name}({json.dumps(tool_input, ensure_ascii=False)[:120]})")

        if name == "fetch_rss":
            return _fetch_rss(tool_input["url"])
        if name == "search_news":
            return _search_news(tool_input["query"])
        if name == "write_briefing":
            return _write_briefing(tool_input["path"], tool_input["content"])
        return json.dumps({"error": f"Unknown tool: {name}"})

    @staticmethod
    def _print_response_summary(response: anthropic.types.Message, round_num: int) -> None:
        tool_calls = [b.name for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]
        print(
            f"  Round {round_num}: stop={response.stop_reason} "
            f"tools={tool_calls} "
            f"text_chars={sum(len(b.text) for b in text_blocks)}"
        )
