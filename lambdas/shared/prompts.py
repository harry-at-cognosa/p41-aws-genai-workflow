"""
Prompt templates for summarization. Lives in code (not config) for v1.0;
can be promoted to DynamoDB or SSM Parameter Store in v2.0 if we want
per-user template overrides or A/B testing.
"""

SYSTEM = (
    "You are a precise document summarizer. Produce summaries that preserve "
    "the document's claims and structure. Do not invent facts. Quote sparingly."
)

USER_TEMPLATE = """\
Summarize the following document.

Output format (markdown):
1. **TL;DR** — two sentences.
2. **Key points** — 5 bullets, each one sentence.
3. **Notable quotes** — up to 2, only if directly material.

Document:
<<<
{document}
>>>
"""


def render_user_message(document: str) -> str:
    return USER_TEMPLATE.format(document=document)
