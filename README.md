# android-kmp-ai-skills

A collection of AI agent skills for **Android and Kotlin Multiplatform (KMP)** development.
Works with any AI coding agent that supports the skills convention — Antigravity, Cursor, Codex, Gemini CLI, and more.

---

## Skills Included

### Custom (in this repo)

These skills are custom-built to enforce specific architectural patterns, libraries, and QA workflows across Android and KMP projects:

| Skill | What it does |
|---|---|
| `android-emulator-qa` | End-to-end QA on emulators/devices — build, install, launch, UI interaction, logcat, crash diagnostics |
| `android-compose-ui` | Compose UI patterns — stability, animations, previews, design systems |
| `android-data-layer` | Data sources, repositories, Room, Ktor, offline-first patterns |
| `android-di-koin` | Koin dependency injection setup for Android/KMP |
| `android-error-handling` | Typed `Result<T, E>` wrapper, error types, extension helpers |
| `android-module-structure` | Module layout, dependency rules, Gradle convention plugins |
| `android-navigation-2` | Type-safe Compose Navigation — routes, nav graphs, cross-feature nav |
| `android-presentation-mvi` | MVI pattern — State, Action, Event, ViewModel, composable split |
| `android-testing` | ViewModel unit tests, Turbine, fake repos, Compose UI tests |
| `git-agentic-commit` | Workflow for creating atomic, buildable, and conventional git commits |

### Official (from Google's `android` CLI)

The following skills are sourced from [Google's official Android developer skills](https://github.com/android/skills).
They are bundled here as a snapshot for machines without the `android` CLI. When the CLI is available, `android skills add --all` runs at install time and always fetches the **latest** version directly from Google.

Here are a few examples of the official skills included in the snapshot (see the [Android skills repository](https://github.com/android/skills) for the full list):

| Skill | What it does |
|---|---|
| `android-cli` | Orchestrate Android tasks via the `android` command-line tool |
| `adaptive` | Adaptive UI for phones, tablets, foldables, and desktop using Compose |
| `agp-9-upgrade` | Upgrade Android projects to AGP 9 |
| `appfunctions` | Expose app workflows as AppFunctions for AI agents and system shortcuts |
| `camera1-to-camerax` | Migrate legacy Camera1/Camera2 to CameraX |
| `edge-to-edge` | Adaptive edge-to-edge support, insets, IME, and system bar fixes |
| `navigation-3` | Jetpack Navigation 3 — deep links, backstacks, scenes, Hilt/Koin |
| `perfetto-trace-analysis` | Analyse Perfetto traces for latency, memory, and jank |
| `styles` | Integrate Jetpack Compose Styles API into a project |
| `... and more` | Plus many other official skills like testing-setup, r8-analyzer, verified-email, etc. |

---

## Install

### Global — all projects on this machine
```bash
curl -sSL https://raw.githubusercontent.com/mohit-0204/android-kmp-ai-skills/main/install.sh | bash
```

### Project-local — only for the current project
```bash
# Run from inside your project directory
curl -sSL https://raw.githubusercontent.com/mohit-0204/android-kmp-ai-skills/main/install.sh | bash -s -- --project
```

The installer will:
1. Detect all AI agents installed on your machine and install skills for each
2. Run `android skills add --all` if the `android` CLI is present
3. Auto-generate `workspace.json` with your SDK paths and AVDs
4. For project-local installs: add `.agents/skills/` to `.gitignore`

---

## Supported Agents

| Agent | Global skills path |
|---|---|
| Antigravity (Google) | `~/.gemini/antigravity/skills/` |
| Gemini CLI | `~/.gemini/skills/` |
| Cursor | `~/.cursor/skills/` |
| OpenAI Codex | `~/.codex/skills/` |
| Continue.dev | `~/.continue/skills/` |

Project-local skills are installed to `.agents/skills/` inside your project root.

---

## After Install

The installer auto-generates `workspace.json` in each skill directory with your machine's SDK paths and AVDs:

```json
{
  "sdk": {
    "root": "/path/to/Android/Sdk",
    "adb": "/path/to/adb",
    "emulator": "/path/to/emulator",
    "python": "/usr/bin/python3"
  },
  "avds": ["YourAVDName"]
}
```

> `workspace.json` is **never committed** to git. It is always generated locally.

---

## Re-generate `workspace.json`

If your SDK changes, re-run detection without reinstalling:

```bash
python3 tools/setup_workspace.py --skill-dir ~/.gemini/antigravity/skills/android-emulator-qa
```

---

## Porting to a New Machine

1. Run the one-liner install above — it handles everything automatically
2. The installer auto-detects your SDK, AVDs, and writes `workspace.json`
3. Done — no manual file editing required in most cases

---

## What is NOT in this repo

- `workspace.json` — generated locally, never committed
