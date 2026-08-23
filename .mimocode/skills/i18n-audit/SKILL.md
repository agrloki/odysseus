---
name: i18n-audit
description: Use when finding and replacing hardcoded English strings in JavaScript files with window.__t() internationalization calls.
---

# i18n Audit

Standard workflow for internationalizing JavaScript files in the Odysseus project.

## Context

- **Locale files**: `static/locales/en.js` and `static/locales/ru.js`
- **i18n function**: `window.__t('key')` or `__t('key')`
- **Pattern**: Hardcoded English strings → locale key → `window.__t('key')` call

## When to Use

- Auditing a JS file for hardcoded English strings
- Adding i18n support to existing JS modules
- Finding missed translations after code changes

## Workflow

### 1. Identify Hardcoded Strings

**Grep patterns to find candidates:**
```bash
grep -n "textContent = '[A-Z]" static/js/<file>.js
grep -n "\.textContent = \"" static/js/<file>.js
grep -n "innerHTML = '" static/js/<file>.js
grep -n "title = '" static/js/<file>.js
grep -n "placeholder = '" static/js/<file>.js
grep -n "alert(" static/js/<file>.js
grep -n "confirm(" static/js/<file>.js
```

**Exclude patterns (already internationalized):**
- `window.__t(` — already using i18n
- `__t(` — already using i18n
- Variable names, not display text
- CSS class names
- Console.log messages

### 2. Create Locale Keys

**Naming convention:**
```
<module>.<element>.<description>
```

Examples:
- `settings.tts.title` → "Text-to-Speech Settings"
- `settings.tts.voice.placeholder` → "Select voice..."
- `cookbook.tasks.status.running` → "Running"

**Add to both locale files:**
```javascript
// en.js
settings: {
  tts: {
    title: "Text-to-Speech Settings",
    voice: {
      placeholder: "Select voice..."
    }
  }
}

// ru.js
settings: {
  tts: {
    title: "Настройки синтеза речи",
    voice: {
      placeholder: "Выберите голос..."
    }
  }
}
```

### 3. Replace in JavaScript

**Before:**
```javascript
element.textContent = 'Text-to-Speech Settings';
```

**After:**
```javascript
element.textContent = window.__t('settings.tts.title');
```

**For conditional fallback:**
```javascript
element.textContent = window.__t && window.__t('settings.tts.title') || 'Text-to-Speech Settings';
```

### 4. Verify

**Syntax check:**
```bash
node --check static/js/<file>.js && echo "Syntax OK"
node --check static/locales/en.js && node --check static/locales/ru.js && echo "Locales OK"
```

**Check for duplicates:**
```bash
grep -o "window\.__t('[^']*')" static/locales/en.js | sort | uniq -d
```

## Common Mistakes to Avoid

1. **Don't translate console.log messages** — those are for debugging
2. **Don't translate CSS class names** — those are identifiers
3. **Don't translate variable names** — only user-visible text
4. **Don't forget fallbacks** — `window.__t('key') || 'English'` for safety
5. **Don't create duplicate keys** — check existing keys first

## Locale File Structure

```javascript
// en.js
window.__locale = {
  app: {
    name: "Odysseus",
    loading: "Loading..."
  },
  settings: {
    title: "Settings",
    // ... nested keys
  },
  // ... other modules
};

// ru.js
window.__locale = {
  app: {
    name: "Одиссей",
    loading: "Загрузка..."
  },
  settings: {
    title: "Настройки",
    // ... nested keys
  },
  // ... other modules
};
```
