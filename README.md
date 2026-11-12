# Annsa plugins

Annsa is the plan your AI agents work from. Annsa is project management and customer feedback software for founders and small teams working with AI agents. Direction for your agents and projects, grounded in your customers and your goals.

Annsa gives your agents eight tools: three that read your ranked work, its specs and your evidence, and five that do the work, add findings, record your decisions, arrange the board and tell customers what shipped.

One `skills/` folder and one MCP config (`.mcp.json`) serve Claude Code, Cursor, Codex and Grok Build. The MCP server is remote (`https://app.annsa.ai/mcp`). You sign in with your browser. There is no API key.

## Install

### Claude Code

```bash
claude plugin marketplace add annsa-ai/annsa-plugins
claude plugin install annsa@annsa-plugins
```

### Cursor

Customize, Add Marketplace, Import from GitHub, paste the repository URL, then add Annsa from the Personal tab.

### Codex

```bash
codex plugin marketplace add annsa-ai/annsa-plugins --ref main
codex plugin add annsa@annsa-plugins
codex mcp login annsa
```

### Grok Build

```bash
grok plugin marketplace add annsa-ai/annsa-plugins
grok plugin install annsa --trust
grok plugin enable annsa
```

### Any other agent (skills only)

```bash
npx skills add annsa-ai/annsa-plugins
```

This installs the skills. Add the MCP server yourself: `https://app.annsa.ai/mcp` (Streamable HTTP, named `annsa`).

### Any MCP client (Cline, Windsurf, VS Code and others)

Annsa is a remote MCP server. Nothing to install and no API key: add this to your client's MCP settings, then sign in when the browser opens.

```json
{
  "mcpServers": {
    "annsa": {
      "url": "https://app.annsa.ai/mcp"
    }
  }
}
```

If your client asks for a transport, choose Streamable HTTP. If it only supports local (stdio) servers, see https://annsa.ai/docs/using-with-coding-tools.

## Enforced principles (Claude Code and Cursor)

A principle you switch to Enforce in Annsa stops the agent's matching shell command before it runs: a deploy, a push or merge to the default branch, an approved PR, a destructive command. The hook is in `hooks/` and loads with the plugin in Claude Code (PreToolUse) and Cursor (beforeShellExecution). Codex and Grok Build don't run it; they follow the principle as a rule.

The hook reads your sign-in from `~/.annsa/token.json`, so run `npx annsa auth` once. It checks commands on your machine, logs each refusal on the principle, and lets the command run if Annsa can't be reached. Set `ANNSA_ENFORCE=0` to switch it off on one machine. It sends your token only to api.annsa.ai, app.annsa.ai or canopy.annsa.ai. It stops honest mistakes, not a determined adversary: it runs as the same user as the agent, so it can't protect its own cache or token from a determined agent.

## First use

Your agent opens a browser to sign in to Annsa. Then ask: "What should I work on?"

## Docs

https://annsa.ai/docs
