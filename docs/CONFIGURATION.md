# Nakama-kun Configuration Manual

Nakama-kun manages settings using `pydantic-settings`. Config values are resolved from the environment, `.env` files, JSON configs, or YAML files.

---

## 1. Environment Variables and Settings Classes

### A. AI Integration Configuration (`AISettings`)
Declared in [config.py](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/ai/config.py):
- **`OPENROUTER_API_KEY`** (SecretStr, required for AI modes): OpenRouter API gateway authorization token.
- **`OPENROUTER_MODEL`** (string, default: `openai/gpt-5`): Model alias or full openrouter identifier.
- **`OPENROUTER_BASE_URL`** (string, default: `https://openrouter.ai/api/v1`): Endpoint target.

### B. RAG System Configuration (`RAGSettings`)
Declared in [rag.py](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/config/rag.py):
- **`RAG_ENABLED`** (boolean, default: `True`): Toggles RAG indexing and search.
- **`RAG_DB_PATH`** (string, default: `.rag`): Directory of persistent vector store data.
- **`RAG_EMBEDDING_PROVIDER`** (string, default: `local`): `local` (BGE-M3 or ONNX fallback), `openai` or `openrouter`.
- **`RAG_EMBEDDING_MODEL`** (string, default: `text-embedding-3-small`): OpenAI embedding path.
- **`RAG_EMBEDDING_API_KEY`** / **`RAG_EMBEDDING_BASE_URL`**: Overrides credentials for OpenAI embedding requests.
- **`RAG_CHUNK_SIZE_LINES`** / **`RAG_CHUNK_OVERLAP_LINES`**: Legacy metrics (replaced by character bounds 800-1200 / 100-200 overlap).

### C. Experience Memory Configuration (`MemorySettings`)
Declared in [memory.py](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/config/memory.py):
- **`MEMORY_ENABLED`** (boolean, default: `True`): Toggles local experience collection.
- **`MEMORY_DB_PATH`** (string, default: `nakama_memory.db`): Path to the SQLite experience database.
- **`MEMORY_VECTOR_DB_PATH`** (string, default: `.nakama_memory_vectors`): Path to semantic memory vectors database.

### D. Model Context Protocol (MCP) Configuration (`MCPSettings`)
Declared in [mcp.py](file:///home/tankaizokuo/Code/Nakama-Kun/src/nakama_kun/config/mcp.py):
- **`MCP_CONFIG_PATH`** (string, default: `mcp_config.json`): Persistent stdio server definition file.
- **`MCP_SERVERS_JSON`** (string, optional): Stringified JSON specifying baseline stdio servers.

---

## 2. Configuration Profiles & Examples

### A. Environment Profile Configuration Example (`.env`)
Create a `.env` file in the workspace root or parent directories:
```bash
# AI Provider
OPENROUTER_API_KEY=sk-or-v1-xxxxxx
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# RAG Configuration
RAG_ENABLED=true
RAG_DB_PATH=.rag
RAG_EMBEDDING_PROVIDER=local

# Memory Configuration
MEMORY_ENABLED=true
MEMORY_DB_PATH=nakama_memory.db
```

### B. Standard Claude MCP Configuration Example (`mcp_config.json`)
Configure stdio subprocess parameters:
```json
{
  "mcpServers": {
    "postgres": {
      "command": "python3",
      "args": ["-m", "nakama_kun.mcp.servers.postgres"],
      "env": {
        "DATABASE_URL": "postgresql://postgres:secret@localhost:5432/nakama"
      }
    },
    "filesystem": {
      "command": "python3",
      "args": ["-m", "nakama_kun.mcp.servers.filesystem"]
    }
  }
}
```

### C. YAML Merging Overlays (`mcp.yaml`)
You can add `mcp.yaml` to dynamically override, filter, or enable servers defined in `mcp_config.json`:
```yaml
servers:
  postgres:
    enabled: true
    env:
      DATABASE_URL: "postgresql://developer:pass@127.0.0.1:5432/prod"
  browser:
    enabled: false
```
If `mcp.yaml` exists, it takes precedence and filters out disabled server configurations.
