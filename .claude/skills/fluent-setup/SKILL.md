---
name: fluent-setup
description: One-time interactive onboarding that creates the learner's personalized language-learning profile — name, target language, native language, current/target CEFR level, timeline, daily minutes, and learning goals. Triggered only when the learner types /fluent-setup. Also handles profile updates and resets for returning users. Must never auto-invoke because re-running can reset progress.
allowed-tools: Read, Write, Bash, AskUserQuestion
disable-model-invocation: true
---

# Language Learning Setup

## Overview

One-time onboarding that seeds all 6 databases in the Fluent data directory. After setup, every other skill reads from those files — this is the bootstrap. Also handles profile updates, progress resets, and **language switching** for returning users.

The data directory is resolved at runtime (not hardcoded to `./data/`):

1. `$FLUENT_DATA_DIR` if set
2. `$CLAUDE_PROJECT_DIR/data/` if that path contains `_active.json` or `learner-profile.json` (clone mode)
3. `./data/` if `./data/_active.json` or `./data/learner-profile.json` exists (clone mode, cwd inside repo)
4. `~/.claude/fluent-data/` otherwise (plugin-install default)

**Per-language structure:** Each target language stores its 6 databases in a separate subdirectory. The active language is tracked in `_active.json` at the base level:

```
~/.claude/fluent-data/
  _active.json                    # {"active_language": "mongolian", "version": 1}
  mongolian/                      # Per-language 6 DBs
    learner-profile.json, ...
  french/
    learner-profile.json, ...
```

Always resolve it via the helper rather than writing literal `data/` paths:

```bash
FLUENT_DATA="$(python3 "${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks/ensure_data_dir.py")"
```

or from Python:

```python
import sys
sys.path.insert(0, f"{PLUGIN_ROOT}/.claude/hooks")
from fluent_paths import ensure_data_dir
DATA = ensure_data_dir()
```

## When to Use

Trigger this skill only when the learner types `/fluent-setup`. The skill is gated with `disable-model-invocation: true` — re-running can reset a learner's progress, so it must never auto-fire from an ambiguous prompt.

Skip this skill if a profile already exists and the learner did not ask to change anything; route them to `/fluent-learn` or `/fluent-progress` instead.

## Instructions

### 1. Check for existing profile

Resolve the data directory first, then probe for `learner-profile.json`:

```bash
DATA_DIR="$(python3 -c "
import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks')
from fluent_paths import data_dir
print(data_dir())
")"
test -f "$DATA_DIR/learner-profile.json" && echo "exists" || echo "new"
```

If it exists, jump to **Profile updates** below. Otherwise continue.

**Note:** `data_dir()` now resolves to the per-language subdirectory (e.g. `~/.claude/fluent-data/mongolian/`). The `_active.json` file at the base level tracks which language is currently active. Old flat structures are auto-migrated on first access.

### 2. Welcome

```markdown
# 🌍 Welcome to Your Personal Language Learning System!

This AI-powered system will help you learn any language through:
- 📊 Systematic progress tracking
- 🧠 Spaced repetition (scientifically proven)
- 🎮 Gamification (streaks, achievements)
- 📈 Adaptive difficulty
- 🎯 Personalized to YOUR goals

**Let's get you set up!** (~5 minutes)
```

### 3. Collect info

Use the `AskUserQuestion` tool to gather questions in batches when possible. Required fields:

1. **Name** — personalizes greetings.
2. **Target language** — the language being learned (e.g. Spanish, French, German, Japanese, Korean, Arabic, Dutch).
3. **Native language** — for translations and explanations.
4. **Other languages spoken** — optional, used to offer cross-language connections.
5. **Current level** — A1 / A2 / B1 / B2 / C1 / C2 / "not sure".
6. **Target level** — where they want to get to.
7. **Timeline** — 3 months / 6 months / 12 months / 2+ years / custom.
8. **Daily study minutes** — 10 / 15 / 30 / 60 / custom.
9. **Learning goal** — travel / work / exam (specify) / living in country / academic / family / interest.
10. **Learning style** — conversational / academic / immersive / balanced (default).
11. **Gamification on/off** — default on.

If the learner picks "not sure" for current level, run a quick 5-question assessment:

1. Basic vocabulary recognition → A1
2. Simple sentence construction → A2
3. Past tense usage → B1
4. Complex subordinate clauses → B2
5. Idiomatic expression → C1

Map score to level: 0-1 correct = A1, 2 = A2, 3 = B1, 4 = B2, 5 = C1.

### 4. Generate the learning plan

Compute expected months to target level:

```
A1 → A2: ~100 hours
A2 → B1: ~150 hours
B1 → B2: ~200 hours
B2 → C1: ~300 hours
C1 → C2: ~400 hours

months = hours_needed / (daily_minutes / 60) / 30
```

Adjust:

- `-10%` time if learner's native language is typologically close to the target (e.g. Dutch ↔ English, Spanish ↔ Italian).
- `-10%` per additional language already known (cap at 30% total).

Present:

```markdown
## 🎉 Setup Complete!

**Your Learning Profile:**
- 👤 Name: {name}
- 🌍 Learning: {target_language}
- 📚 Native: {native_language}
- 📊 Level: {current} → {target}
- 📅 Timeline: {timeline}
- ⏱️ Daily time: {minutes} min
- 💡 Goal: {goal}

## 📋 Personalized Plan

**Estimated time:** {months} months
**Total study hours:** ~{hours} hours

### Weekly Schedule
**Daily:**
- 🔄 `/fluent-review` — spaced repetition ({X} min)
- 📚 `/fluent-vocab` — new vocabulary ({Y} min)

**Alternating:**
- 📝 `/fluent-writing` (Mon/Wed/Fri)
- 🗣️ `/fluent-speaking` (Tue/Thu/Sat)
- 📖 `/fluent-reading` (Sun)

**Weekly:**
- 📊 `/fluent-progress` — check stats (5 min)

### Milestones
- Month 1: {reasonable short-term}
- Month 3: {quarter-way}
- Month 6: {half-way}
- Target date: {target_level}!

### Next Steps
1. Start now — type `/fluent-learn`
2. Daily habit — `/fluent-review` every day
3. Weekly — `/fluent-progress` to see stats
4. Stay consistent — even 10 min daily beats 2 hours weekly

**Your journey to {target_language} fluency starts now!** 🚀
```

### 5. Write databases

Start from the templates in `data-examples/`. **First**, set the active language so that `data_dir()` resolves to the correct per-language subdirectory:

```bash
LANG_SLUG="$(python3 -c "
import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks')
from fluent_paths import set_active_language
print(set_active_language('${TARGET_LANGUAGE}'))
")"
```

Then resolve the target directory via `fluent_paths.ensure_data_dir()` (it creates the language subdirectory if missing), and create these 6 files inside it:

- `learner-profile.json` — fill all fields from the interview.
- `progress-db.json` — empty stats.
- `mistakes-db.json` — empty `error_patterns`.
- `mastery-db.json` — `skills_mastery` entries with `mastery_level: 0` for each skill.
- `spaced-repetition.json` — empty queues, `daily_limits.review_items_per_day: 20`.
- `session-log.json` — empty `sessions` array, `total_sessions: 0`.

Use the Write tool for each. Do not call `update-db.py` — that script is for session updates, not bootstrapping.

### 6. Optional first lesson

```markdown
## 🎓 Want to start your first lesson now?

A quick 5-10 min intro session to learn your first 10 words and get familiar with the system.

Type "yes" to start, "later" to begin on your own.
```

If yes, hand off to the `fluent-learn` skill.

## Profile Updates (existing profile)

```markdown
# 👋 Welcome back, {name}!

You already have a learning profile for **{target_language}**.

What would you like to do?

1. **Update profile** — change goals, timeline, or preferences
2. **View current plan** — see your learning schedule
3. **Reset progress** — start fresh for this language (⚠️ erases this language's progress only!)
4. **Switch language** — start or resume a different language (keeps all progress)
5. **Cancel** — keep everything as is

**Type 1, 2, 3, 4, or 5:**
```

- **1** — ask which field, update only that field, preserve the rest.
- **2** — render the plan section from current data. Read-only.
- **3** — confirm twice. This deletes every file in the resolved **per-language** data directory. Other languages are unaffected. Back up first:

  ```bash
  DATA_DIR="$(python3 -c "
  import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks')
  from fluent_paths import data_dir
  print(data_dir())
  ")"
  TS="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$DATA_DIR/.backups/pre-reset-$TS"
  cp "$DATA_DIR"/*.json "$DATA_DIR/.backups/pre-reset-$TS/"
  ```

  Then restart setup from Step 2.

- **4** — **Switch language.** See "Language Switch" section below.

- **5** — exit cleanly.

## Language Switch (option 4)

List existing languages and let the learner choose:

```bash
LANGUAGES="$(python3 -c "
import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks')
from fluent_paths import list_languages
print('\n'.join(list_languages()))
")"
```

```markdown
## 🌐 Switch Language

Your languages:
{numbered list of existing language slugs}

Or start a new language.

**Type a number to switch, or type the name of a new language:**
```

**If learner picks an existing language:**

```bash
python3 -c "
import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT:-${CLAUDE_PROJECT_DIR:-.}}/.claude/hooks')
from fluent_paths import set_active_language
print(set_active_language('${CHOSEN_LANGUAGE}'))
"
```

Then read that language's profile and greet them:

```markdown
# ✅ Switched to {target_language}!

**Your {target_language} progress:**
- 📊 Level: {current} → {target}
- 🔥 Streak: {X} days
- 📚 Sessions: {Y}

Type `/fluent-learn` to start practicing!
```

**If learner types a new language:** collect the target language name, call `set_active_language()`, then proceed with the full setup flow from Step 3 (collect name, native language, level, etc.) and write 6 fresh DB files. The old language's data remains untouched in its subdirectory.

## Examples

### Example 1 — first-time setup flow

Learner runs `/fluent-setup`. After collecting all 11 answers, compute months, generate plan, write 6 JSON files, offer first lesson.

### Example 2 — returning-user profile reset

Learner: "reset my progress, I want to start over"

> You're about to reset your **Mongolian** progress:
> - 42 sessions
> - 6-day streak
> - 287 vocabulary items
> - 12 mastered patterns
>
> Your other languages are unaffected.
>
> This is irreversible. Type `RESET` (all caps) to confirm, or anything else to cancel.

### Example 3 — switching to a new language

Learner: "I want to learn French too"

> ## 🌐 Switch Language
>
> Your languages:
> 1. mongolian (active)
>
> Or start a new language.
>
> **Type a number to switch, or type the name of a new language:**

Learner types "French":

> 🇫🇷 Setting up French! Let's collect your learning preferences...
>
> *(proceeds with full setup flow — name, native language, level, etc.)*
>
> Mongolian progress is saved — switch back anytime with `/fluent-setup`.

### Example 4 — switching to an existing language

Learner: "switch back to Mongolian"

> ## 🌐 Switch Language
>
> Your languages:
> 1. mongolian
> 2. french (active)
>
> **Type a number to switch, or type the name of a new language:**

Learner types "1":

> ✅ Switched to Mongolian!
>
> **Your Mongolian progress:**
> - 📊 Level: A1 → B2
> - 🔥 Streak: 6 days
> - 📚 Sessions: 42
>
> Type `/fluent-learn` to start practicing!

## Critical Rules

- **Never auto-invoke.** Re-running this can reset a learner's progress. Must be an explicit `/fluent-setup`.
- **Confirm twice before reset.** "This will erase X days of progress, Y sessions, and Z mastered words in {language}. Your other languages are unaffected. Proceed? (yes/no)".
- **Always call `set_active_language()` before writing DB files.** This ensures `data_dir()` resolves to the correct per-language subdirectory.
- **Always seed all 6 files** — every other skill assumes they exist in the per-language directory.
- **Back up before reset.** Hooks may not fire here; back up manually to `.backups/pre-reset-<timestamp>/` within the language subdirectory.
- **Don't invent data.** Start every file empty — progress, mistakes, mastery all start at zero. The system builds up from real sessions.
- **Language switching is non-destructive.** Switching to a new language creates a fresh set of DBs without touching other languages' data.
