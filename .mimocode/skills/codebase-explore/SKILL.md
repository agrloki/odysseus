---
name: codebase-explore
description: Use when exploring the Odysseus project to understand architecture, patterns, or how a specific feature is implemented.
---

# Codebase Exploration

Standard workflow for understanding the Odysseus project structure and architecture.

## Context

- **Project root**: `/home/loki/PTMP/odysseus`
- **Backend**: FastAPI (Python) in `src/`, `routes/`, `services/`
- **Frontend**: Vanilla JS in `static/js/`
- **Docker**: Container `odysseus-odysseus-1` at `localhost:7000`

## When to Use

- Understanding how a feature is implemented
- Planning new feature integration
- Debugging issues by tracing code paths
- Onboarding to unfamiliar parts of the codebase

## Workflow

### 1. Define Scope

**Be specific about what to explore:**
- "How does the TTS system work?"
- "How are routes registered?"
- "How does the agent mode function?"
- "How are integrations structured?"

### 2. Entry Points

**Start with key files:**
- `app.py` — FastAPI app setup, route registration
- `src/agent_loop.py` — Main agent loop logic
- `src/settings.py` — Configuration and API keys
- `routes/` — Backend API endpoints
- `static/js/*.js` — Frontend modules

### 3. Read Key Files

```bash
# Find file
glob "**/*.py" pattern="<filename>"

# Read file
read filePath="/home/loki/PTMP/odysseus/src/<path>"
```

### 4. Trace Dependencies

**Grep for imports and references:**
```bash
grep pattern="from src\." include="*.py"
grep pattern="import.*<module>" include="*.py"
grep pattern="<function_name>" include="*.py"
```

### 5. Understand Patterns

**Common architectural patterns:**
- **Routes**: FastAPI routers in `routes/`, registered in `app.py`
- **Services**: Business logic in `services/`, called by routes
- **Models**: Data models in `src/` or `models/`
- **Static files**: Frontend JS in `static/js/`, CSS in `static/style.css`

### 6. Document Findings

**Structure the summary:**
1. **Purpose**: What does this module/feature do?
2. **Key files**: List the main files involved
3. **Data flow**: How data moves through the system
4. **Dependencies**: What it depends on, what depends on it
5. **Integration points**: How to extend or modify it

## Example Exploration

**Request**: "Explore the TTS architecture"

**Steps**:
1. Find TTS-related files:
   ```bash
   glob "**/*.py" pattern="*tts*"
   grep pattern="tts" include="*.py"
   ```

2. Read key files:
   - `services/tts/tts_service.py`
   - `routes/tts_routes.py`
   - `static/js/settings.js` (TTS settings UI)

3. Trace dependencies:
   - TTS service → database models
   - TTS routes → TTS service
   - Frontend → TTS API

4. Produce summary:
   - Purpose: Text-to-speech synthesis
   - Engines: Piper, Kokoro, Silero
   - API: `/api/tts/speak`, `/api/tts/voices`
   - Settings: Stored in `model_endpoints` table

## Tips

- **Start broad, then narrow**: Read app.py first, then drill into specific modules
- **Follow the data**: Trace from API request → route → service → database
- **Check tests**: `tests/` directory reveals expected behavior
- **Use grep strategically**: Find where a function is called, not just defined
- **Read comments**: They explain "why", not just "what"
