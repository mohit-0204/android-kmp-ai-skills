---
name: git-agentic-commit
description: |
  Workflow for creating atomic, buildable, and conventional git commits.
  Supports two modes:
    - Plan-Aware: aligns commits to phases in PHASED_IMPLEMENTATION_PLAN.md
    - Semantic: smart package/feature clustering when no plan exists.
  Ensures tests and migrations are always co-committed with their source.
  Every commit must pass the build independently (Stash-and-Build).
---

# Git Agentic Commit

## Overview

This skill groups all uncommitted working-tree changes into **atomic, independently buildable commits** following the Conventional Commits standard.

It operates in two modes, automatically selected:

| Mode | Triggered when | Strategy |
|------|---------------|----------|
| **Plan-Aware** | `PHASED_IMPLEMENTATION_PLAN.md` (or `ROADMAP.md`, `PLAN.md`) exists in the repo | Groups files by implementation phase using artifact names extracted from each phase body |
| **Semantic-Only** | No plan file found | Groups files by package directory + feature cluster. Tests, migrations, config co-grouped with their source. |

---

## Step 1 — Run the Analyzer

Always start by running:

```bash
python3 skills/git-agentic-commit/scripts/analyze_changes.py
```

Run from the **project root** (where `.git` lives). Use `--debug` to see per-file scoring.

The script produces a ranked list of proposed commits with:
- Phase number and title (Plan-Aware mode)
- Exact files to `git add`
- A ready-to-use conventional commit message

---

## Step 2 — Grouping Rules

### 2.1 Plan-Aware: Matching Files to Phases

The agent extracts **artifact names from each phase body** — not the phase title.
Artifact types matched:

- **PascalCase class names** — e.g., `SearchQueryEntity`, `CacheOrchestratorService`
- **SQL migration file names** — e.g., `V7__add_search_queries.sql`
- **Package segments in backticks** — e.g., `` `cache` ``, `` `ingestion` ``

Each file is scored against every phase. The highest-scoring phase wins. Ties go to the **earlier phase** (lower phase number).

> **Phase ordering is enforced.** Phase 1 is always committed before Phase 2, etc.
> A file from Phase 3 will never appear in Commit 1.

### 2.2 Semantic-Only: Feature Clustering

Without a plan, files are clustered by their **immediate package directory**:
- All files in `src/.../cache/` → one "Feature: cache" commit.
- All files in `src/.../ingestion/` → one "Feature: ingestion" commit.

### 2.3 Co-Grouping Rules (apply in both modes)

These rules run **after** initial assignment and cannot be overridden manually:

| Secondary file type | Co-grouped with |
|--------------------|-----------------|
| Test (`*Test.java`, `*Test.kt`) | The source class it tests (matched by stripping `Test` suffix) |
| SQL migration (`V{n}__*.sql`) | The phase/cluster whose entity consumes the migration |
| Build file (`pom.xml`, `build.gradle`) | The **earliest** phase/cluster that has a scored match |
| Config (`application.properties`, `*.yml`) | The **earliest** phase/cluster that has a scored match |
| Docs (`*.md`) | The phase/cluster they describe, or a standalone `docs` commit |

> **Shared modified files**: If a single file (e.g., `application.properties`) spans multiple phases, commit it with the **earliest phase** that touches it. Add a note in the commit body if it also serves later phases.

---

## Step 3 — Commit Message Rules

The analyzer generates the full message. **Never use a placeholder**. Always match the project's established style.

### Subject line format
```
type(scope): lowercase description based on file changes
```

- `type` — `feat`, `fix`, `test`, `build`, `docs`, `chore`, `refactor`
- `scope` — **domain package** in lowercase: `cache`, `ingestion`, `auth`, `backend`, `core`
  - Use the dominant source package directory, **not** the phase title word
  - Never use file names, dotted paths, or generic words like `feature` as scope
- `description` — **All lowercase**, imperative, concise
  - ❌ `feat(cache): phase 1 - add query tracking table` — no phase prefix
  - ❌ `feat(cache): Add query tracking table` — no capital letters at the start
  - ✅ `feat(cache): implement search query entity, search query normalizer and search query repository` (explains what was ACTUALLY done based on the files)

### Commit body format
Always include a bullet-list body:
```
- Verb Noun ... (sentence case, no trailing period)
- Verb Noun ...
```

Each meaningful source file, migration, test group, or config change gets its own bullet.

### Full example (matching project history style)
```
feat(cache): implement search query entity and search query repository

- Define search query entity as the JPA persistence model
- Add search query repository for database access
- Introduce search query status enum for state tracking
- Implement search query normalizer for consistent data transformation
- Add Flyway migration to create search_queries table
- Update application.properties with cache configuration properties
```

### Git command with body
```bash
git commit -m "feat(cache): implement search query entity and search query repository" \
  -m "- Define search query entity as the JPA persistence model" \
  -m "- Add search query repository for database access"
```

### Type usage
| Type | When |
|------|------|
| `feat` | New behaviour, new class, new endpoint |
| `build` | Dependency changes (`pom.xml`, `build.gradle`) only |
| `docs` | Documentation-only changes |
| `test` | Test-only commit (rare — prefer co-committing with source) |
| `chore` | Housekeeping: `.gitignore`, project init, mockito extensions |

---

## Step 4 — Automated Stash-and-Build Execution

The analyzer includes an `--execute` flag that automates the verification workflow. **This is the primary way to commit.**

```bash
python3 scripts/analyze_changes.py --execute
```

For each proposed commit, the script will automatically:
1. `git add` the files for that group.
2. `git stash push --keep-index --include-untracked` to hide everything else.
3. Run the project build (`mvn compile` or `./gradlew assemble`).
4. If the build **PASSES**: executes `git commit` with the generated message and pops the stash.
5. If the build **FAILS**: aborts immediately, pops the stash, and leaves the files staged so you can fix the issue.

> **Atomic Build Rule**: The script strictly enforces that no commit is made unless the exact files in that commit can compile independently.

---

## Step 5 — User Review & Execution

Before passing `--execute`, you should present the plan to the user:

1. Run the script **without** `--execute` to generate the proposal.
2. Present the full commit list to the user.
3. Highlight any anomalies (e.g., a shared file like `application.properties` that might need manual splitting, or tests without source code).
4. **Ask for confirmation.**
5. Once the user approves, run the script **with** `--execute` to finalise the commits safely.

---

## Safety Checks

- Never commit a partial feature (e.g., entity without repository, or migration without entity)
- Never commit a test without its source
- Never commit a config key without the code that reads it
- Always unlock stash with `git stash pop` even if build fails
- If a phase is empty (no files matched), skip it silently — do not create an empty commit
