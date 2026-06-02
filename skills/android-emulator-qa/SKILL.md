---
name: "android-emulator-qa"
description: "Use when validating Android/KMP feature flows on an emulator or device: adb-driven launch, UI interaction, UI-tree inspection, screenshots, logcat capture, and build/install."
---

# Android Emulator QA

Validate Android app flows using adb for launch, input, UI-tree inspection, screenshots, and logs.

---

## ⚠️ MANDATORY FIRST STEP — Read `workspace.json`

**Before doing ANYTHING else**, read `workspace.json` in this skill's directory. It contains machine-specific SDK configuration:
- `sdk.adb` — path to adb
- `sdk.emulator` — path to the emulator binary
- `avds` — list of available virtual device names

This file is **auto-generated at install time** and is never committed to git.
On a new machine, re-run the installer to regenerate it automatically.

> **How to read it:**
> ```bash
> cat <skill_dir>/workspace.json
> ```

---

## When to Use This Skill

- QA a feature flow end-to-end on an emulator or physical device.
- Reproduce a UI bug by driving navigation via adb input events.
- Inspect UI element bounds to verify layout correctness.
- Capture screenshots as build/feature evidence.
- Collect logcat output while reproducing a crash or unexpected behaviour.
- Build and install a specific variant (debug/release/staging) quickly.

---

## Step 0 — Pre-Flight Checks

Always do these BEFORE any QA session:

```bash
# 1. Check connected devices / emulators
adb devices

# 2. If no emulator running, list available AVDs
emulator -list-avds

# 3. Start an AVD
emulator -avd <avd_name> &

# 4. Wait for device to boot
adb wait-for-device shell getprop sys.boot_completed
```

---

## Step 1 — Build & Install

> Use `android layout` or read the open project in the workspace to determine the project type and module.

### KMP / Compose Multiplatform projects

```bash
cd <project_root>

# See all installable tasks
./gradlew tasks --all | grep -i install

# Install debug variant
./gradlew :composeApp:installDebug --console=plain --quiet
```

### Standard Android projects

```bash
cd <project_root>

# Install debug
./gradlew :app:installDebug --console=plain --quiet
```

> **Build flags for diagnosis (use when build fails):**
> `./gradlew :<module>:installDebug --stacktrace --info`

Or use the helper script for a one-shot build + install + launch:
```bash
python3 <skill_dir>/scripts/install_and_launch.py \
    --project <project_root> \
    --serial <device_serial>
```

---

## Step 2 — Launch the App

```bash
# Find the package name from build.gradle / build.gradle.kts
adb -s <serial> shell pm list packages | grep -i <app_keyword>

# Resolve the launchable activity
adb -s <serial> shell cmd package resolve-activity --brief <package.name>

# Launch
adb -s <serial> shell am start -n <package.name>/.<ActivityName>

# Force-stop and relaunch (clean state)
adb -s <serial> shell am force-stop <package.name>
adb -s <serial> shell am start -n <package.name>/.<ActivityName>
```

---

## Step 3 — Drive UI with adb Input

```bash
# Tap (always use UI-tree coordinates, NOT screenshot guesses)
adb -s <serial> shell input tap <x> <y>

# Swipe (avoid edges — stay 150-200px from left/right to prevent back gesture)
adb -s <serial> shell input swipe <x1> <y1> <x2> <y2> <duration_ms>

# Type text
adb -s <serial> shell input text "your_text_here"

# Key events
adb -s <serial> shell input keyevent 4    # Back
adb -s <serial> shell input keyevent 3    # Home
adb -s <serial> shell input keyevent 82   # Menu
adb -s <serial> shell input keyevent 66   # Enter
adb -s <serial> shell input keyevent 111  # Escape

# Long press
adb -s <serial> shell input swipe <x> <y> <x> <y> 1000
```

---

## Step 4 — UI Tree Inspection & Coordinate Picking

**Rule: ALWAYS derive tap coordinates from the UI tree, never guess from a screenshot.**

```bash
# Get the full UI layout tree as JSON (includes text, contentDesc, bounds, center per element)
android layout --pretty

# Get only elements that changed since last call (saves context, good for step-by-step flows)
android layout --diff

# Resolve x y coordinates of a UI element directly by its text or content-desc
android screen resolve "Button Text or Content Desc"

# Combine resolve + tap in one line
adb -s <serial> shell input tap $(android screen resolve "Submit")
```

> **If element not found in `android layout`:** The screen may contain a WebView or animation.
> Fall back to `android screen capture --annotate` to visually identify elements by numbered labels.
> Use `android screen resolve --screen <annotated.png> --string "#3"` to get coordinates for label #3.

> **If still not found:** Check for scrollable containers. Swipe down, re-dump with `android layout --diff`, and re-search.

---

## Step 5 — Screenshots

```bash
# Capture using the Android CLI (primary — handles pull automatically)
android screen capture -o /tmp/screenshot_$(date +%H%M%S).png

# Annotated screenshot (adds numbered labels for element identification)
android screen capture --annotate -o /tmp/annotated_$(date +%H%M%S).png

# Manual adb fallback (when android-cli is unavailable)
adb -s <serial> exec-out screencap -p > /tmp/screen_$(date +%H%M%S).png
```

---

## Step 6 — Logcat

```bash
# Clear existing logs first
adb -s <serial> logcat -c

# Stream logs for specific package only (recommended — uses helper script)
python3 <skill_dir>/scripts/logcat_filter.py \
    --serial <serial> --package <package.name>

# Stream logs with pid manually
PID=$(adb -s <serial> shell pidof -s <package.name>)
adb -s <serial> logcat --pid $PID

# Save crash buffer only
adb -s <serial> logcat -b crash > /tmp/crash_log.txt

# Stream with tag filter
adb -s <serial> logcat -s MyAppTag:V *:S

# Save all logs to file
adb -s <serial> logcat -d > /tmp/logcat_$(date +%H%M%S).txt
```

---

## Step 7 — Common Diagnostic Checks

```bash
# Check app is installed
adb -s <serial> shell pm list packages | grep <package>

# Check memory usage
adb -s <serial> shell dumpsys meminfo <package.name>

# Check ANRs / crashes
adb -s <serial> shell dumpsys activity | grep -A 5 "FAILED"

# Check if activity is in foreground
adb -s <serial> shell dumpsys activity activities | grep "mResumedActivity"

# List recently crashed packages
adb -s <serial> logcat -b crash -d | grep "FATAL EXCEPTION" | tail -20

# Check network connectivity from device
adb -s <serial> shell ping -c 3 8.8.8.8
```

---

## Scripts Reference

All scripts live in `<skill_dir>/scripts/`. The `<skill_dir>` path is wherever this skill is installed on the current machine (e.g., `~/.gemini/antigravity/skills/android-emulator-qa/`).

| Script | Usage | Purpose |
|---|---|---|
| `install_and_launch.py` | `python3 install_and_launch.py --project <path> --serial <serial>` | One-shot: build, install, and launch an Android/KMP app. Auto-detects project type; reads `workspace.json` for the `adb` path. |
| `logcat_filter.py` | `python3 logcat_filter.py --serial <serial> --package <pkg>` | Stream logcat filtered by package name with color-coded severity levels. |

---

## Porting to a New Machine

When moving to a new machine (Windows, Mac, Linux):

1. Run the one-liner install from the GitHub repo — it handles everything automatically:
   ```bash
   curl -sSL https://raw.githubusercontent.com/mohit-0204/android-kmp-ai-skills/main/install.sh | bash
   ```
2. The installer auto-detects your SDK, `adb`, `emulator`, and AVDs, then writes `workspace.json`.
3. If auto-detection missed something, edit `workspace.json` manually:
   - `sdk.adb` — path to adb
   - `sdk.emulator` — path to emulator
   - `avds` — run `emulator -list-avds` to get the list

> `workspace.json` is never committed to git. It is always generated locally.
