# grok-mcp

MCP server for searching X (Twitter) in real-time via xAI Grok live search.

## Setup

```bash
cp x-mcp/.env.example x-mcp/.env
# Fill in your XAI_API_KEY
uv sync
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_x(query)` | Search X posts by keyword / hashtag |
| `get_user_tweets(username)` | Get recent tweets from a user |
| `get_mentions(username)` | Get recent mentions of a user |
| `get_trending_topic(topic)` | Summarize what's being said about a topic |

## Antigravity CLI integration

Add to the project `.agents/mcp_config.json` (or the user-level `~/.gemini/config/mcp_config.json`):

```json
"mcpServers": {
  "grok-mcp": {
    "command": "uv",
    "args": ["run", "--directory", "/path/to/embodied-agy", "--package", "x-mcp", "x-mcp"],
    "env": {}
  }
}
```
