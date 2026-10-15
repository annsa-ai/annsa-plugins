# Annsa plugins

Annsa is the source of direction for your agents.

One `skills/` folder and one MCP config (`.mcp.json`) serve Claude Code, Codex, Cursor and Grok Build. The MCP server is remote (`https://app.annsa.ai/mcp`). You sign in with your browser. There is no API key.

## Install

### Claude Code

```bash
claude plugin marketplace add annsa-ai/plugins
claude plugin install annsa@annsa-plugins
```

### Codex

```bash
codex plugin marketplace add annsa-ai/plugins --ref main
codex plugin add annsa@annsa-plugins
codex mcp login annsa
```

### Cursor

Customize, Add Marketplace, Import from GitHub, paste the repository URL, then add Annsa from the Personal tab.

### Grok Build

```bash
grok plugin marketplace add annsa-ai/plugins
grok plugin install annsa --trust
grok plugin enable annsa
```

### Any other agent (skills only)

```bash
npx skills add annsa-ai/plugins
```

This installs the skills. Add the MCP server yourself: `https://app.annsa.ai/mcp` (Streamable HTTP, named `annsa`).

## First use

Your agent opens a browser to sign in to Annsa. Then ask: "What should I work on?"

## Docs

https://annsa.ai/docs
