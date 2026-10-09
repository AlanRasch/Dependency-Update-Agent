"""Optional: ask Claude to write a short plain-language summary of the update report.

Needs the ANTHROPIC_API_KEY environment variable and the anthropic package.
Without a key, the agent works normally and simply has no summary.
"""

from __future__ import annotations

import os
from typing import Callable

SYSTEM_PROMPT = (
    "You write short pull request notes for dependency updates. Given the list of updated packages "
    "and test output, write at most 5 bullet points: what changed, the risk level, and what a reviewer "
    "should check. Plain language, no preamble."
)


def make_summarizer() -> Callable[[str], str] | None:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    import anthropic  # imported only when used

    client = anthropic.Anthropic(api_key=api_key)
    model = os.getenv("DEP_MODEL", "claude-sonnet-5-5")

    def summarize(text: str) -> str:
        reply = client.messages.create(
            model=model, max_tokens=400, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        return "".join(block.text for block in reply.content if block.type == "text").strip()

    return summarize
