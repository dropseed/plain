---
name: plain-guide
description: Answer questions about the Plain framework by researching docs and source code. Use when asked "how do I...", "does Plain support...", or "how does X work?" questions.
---

# Plain Guide

Research the user's question using `plain docs` and source code, then provide a clear answer.

## 1. Use a subagent for research

Always use the Agent tool to research the question. You almost never know the exact package and section name ahead of time, so let the subagent discover them. This also keeps research output out of the main conversation.

Use the Agent tool with a prompt like:

> Research this Plain framework question: {question}
>
> Start by discovering where the answer lives:
>
> - `uv run plain docs --search <term>` — find relevant packages/sections
> - `uv run plain docs <name> --outline` — see section headings for a package
>
> Then read the relevant content:
>
> - `uv run plain docs <name> --section <section>` — specific section
> - `uv run plain docs <name> --api` — public API surface
> - Use Grep/Read to examine source code when docs are insufficient
>
> Return a clear answer with:
>
> - Working code examples (with imports)
> - Which packages are involved
> - Any gotchas or common mistakes

## 2. Answer the question

- Lead with the answer, not a summary of your research
- Include copy-paste ready code examples with imports
- If the answer spans multiple packages, explain how they connect
- If the user is using Django terminology, translate to Plain equivalents
- If a needed package isn't installed, mention `/plain-install`
- Do NOT fabricate APIs — if unsure, verify with `--api` first
