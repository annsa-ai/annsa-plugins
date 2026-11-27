# Annsa plugins

Annsa is the plan your AI agents work from. Annsa is project management and customer feedback software for founders and small teams working with AI agents. Direction for your agents and projects, grounded in your customers and your goals.

Annsa gives your agents eight tools: three that read your ranked work, its specs and your evidence, and five that do the work, add findings, record your decisions, arrange the board and tell customers what shipped.

One `skills/` folder and one MCP config (`.mcp.json`) serve Claude Code, Cursor, Codex and Grok Build. The MCP server is remote (`https://app.annsa.ai/mcp`). You sign in with your browser. There is no API key.

## Skills

- **annsa-working**: take the next priority, follow the plan, and prove what shipped. Read at the start of every session.
- **annsa-spec**: write a spec from your customers' feedback, with Done When lines your agent has to prove.
- **annsa-decisions**: when to bring a decision to you, and how to follow your answer.

The versions, and where each comes from, are in `skills/SOURCE.md`.

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

## First use

Your agent opens a browser to sign in to Annsa. Then ask: "What should I work on?"

## What's new

- **1.1.0:** Your agent writes Done When lines it can prove the day the work ships: one outcome per line, and anything that needs time to show becomes an experiment with a date. Marketing posts ship with their live link. Your agent can read and set your custom fields, like Form, and ask you to close a finished cycle or bet.

## Docs

https://annsa.ai/docs
