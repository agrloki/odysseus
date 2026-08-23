---
name: docker-deploy
description: Use when deploying local file changes to the Odysseus Docker container. Standardizes the edit → syntax check → docker cp → restart workflow.
---

# Docker Deploy

Standard workflow for deploying file changes to the Odysseus Docker container.

## Configuration

- **Container**: `odysseus-odysseus-1`
- **Password**: `rt67we45`
- **Base path**: `/app/` inside container
- **Local paths**: 
  - `/home/loki/PTMP/odysseus` (project root)
  - `/home/loki/odysseus` (working dir, symlink)

## When to Use

- After editing any file that needs to be visible in the running Odysseus instance
- After fixing a bug in backend (Python) or frontend (JS/HTML) code
- When deploying new routes, services, or static assets

## Deploy Workflow

### 1. Syntax Check (for JS files)

```bash
node --check static/js/<filename>.js && echo "Syntax OK"
```

For locale files:
```bash
node --check static/locales/en.js && node --check static/locales/ru.js && echo "Syntax OK"
```

### 2. Copy to Container

**Single JS file:**
```bash
echo "rt67we45" | sudo -S docker cp static/js/<filename>.js odysseus-odysseus-1:/app/static/js/<filename>.js
```

**Locale files (both):**
```bash
echo "rt67we45" | sudo -S docker cp static/locales/en.js odysseus-odysseus-1:/app/static/locales/en.js && echo "rt67we45" | sudo -S docker cp static/locales/ru.js odysseus-odysseus-1:/app/static/locales/ru.js
```

**Python file:**
```bash
echo "rt67we45" | sudo -S docker cp src/<path>.py odysseus-odysseus-1:/app/src/<path>.py
```

**Entire directory:**
```bash
echo "rt67we45" | sudo -S docker cp static/js/. odysseus-odysseus-1:/app/static/js/
```

### 3. Restart (when needed)

```bash
echo "rt67we45" | sudo -S docker compose restart odysseus
```

**Restart is required for:**
- Python backend changes (routes, services, models)
- HTML template changes
- New files added

**Restart is NOT required for:**
- JS/CSS static file changes (browser refresh is sufficient)
- Locale file changes (browser refresh is sufficient)

### 4. Verify

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7000/
```

Or check logs:
```bash
echo "rt67we45" | sudo -S docker logs odysseus-odysseus-1 --tail 20
```

## Common Patterns

### Full JS Deploy (check + copy + verify)
```bash
cd /home/loki/odysseus && node --check static/js/cookbook.js && echo "Syntax OK" && echo "rt67we45" | sudo -S docker cp static/js/cookbook.js odysseus-odysseus-1:/app/static/js/cookbook.js && echo "Copied"
```

### Deploy + Restart
```bash
echo "rt67we45" | sudo -S docker cp static/js/slashCommands.js odysseus-odysseus-1:/app/static/js/slashCommands.js && echo "rt67we45" | sudo -S docker compose restart odysseus
```

### Deploy Multiple Files + Restart
```bash
echo "rt67we45" | sudo -S docker cp static/js/. odysseus-odysseus-1:/app/static/js/ && echo "rt67we45" | sudo -S docker cp static/locales/. odysseus-odysseus-1:/app/static/locales/ && echo "rt67we45" | sudo -S docker compose restart odysseus
```

## Troubleshooting

**If container is not running:**
```bash
echo "rt67we45" | sudo -S docker compose up -d
```

**If port 7000 is occupied:**
```bash
echo "rt67we45" | sudo -S docker compose down && echo "rt67we45" | sudo -S docker compose up -d
```

**Check container status:**
```bash
echo "rt67we45" | sudo -S docker ps | grep odysseus
```
