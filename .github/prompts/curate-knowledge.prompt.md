---
name: curate-knowledge
description: Knowledge maintenance session - entry coverage, drafting, description, drift and feature boundaries, with human-approved promotion.
argument-hint: "health | entries | build <MetadataType> | describe | drafts | drift | feature <slug>"
agent: knowledge-curator
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'knowledge/*']
---

Run the requested mode through the
[curate-knowledge skill](../skills/curate-knowledge/SKILL.md). For interactive Feature
authoring specifically, use [/author-feature](author-feature.prompt.md).
