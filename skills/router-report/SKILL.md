---
name: router-report
description: Summarize Claude Code model usage (tokens, estimated cost, lanes, effort) and smart-router decisions over a recent window. Use when the user asks about model usage, spend, which models or lanes ran, or runs /router-report.
argument-hint: "[--hours N] [--project TEXT]"
allowed-tools: Bash(~/.claude/router/bin/router-report:*)
---
Run this and show the user its output as-is:

```bash
~/.claude/router/bin/router-report --format markdown $ARGUMENTS
```

After the report, add at most three short observations, and only when the numbers support them. Examples:
- one lane or model dominates the estimated cost
- a lane/model mismatch appears (an agent did not run on its configured model)
- many escalations or BLOCKED actions
- most work ran on the main session rather than on router lanes

Do not recompute or restate the tables. Costs are API-equivalent estimates, not the user's bill.
