---
name: publish-wiki
description: Publish a solution's three files or a delivery document to the existing Azure DevOps Wiki.
argument-hint: "<solution directory, delivery document, or topic> [itemId=<ID>] [wiki=<name>] [path=<existing wiki path>]"
agent: developer
tools: ['read', 'search', 'edit/editFiles', 'execute/runInTerminal', 'vscode/askQuestions', 'ado-readonly/*']
---

Use the [publish-wiki skill](../skills/publish-wiki/SKILL.md) for the requested source and scope.
The request authorizes its scoped page/index writes and the existing delivery Story link.
Read full live pages, preserve manual content, and reuse stable addresses. Publish solution
content only for confirmed production-deployed scope. Return the main URL and actual page/link
outcomes, including any partial failure. The skill owns discovery, conflicts, and verification.
