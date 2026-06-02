#!/usr/bin/env bash
# android-kmp-ai-skills installer — Linux/macOS
#
# Usage:
#   bash install.sh                    # global install
#   bash install.sh --project          # project-local install (run from project root)
#   bash install.sh --workspace=/path  # explicit workspace root
#
# One-liner:
#   curl -sSL https://...install.sh | bash -s -- --project

set -euo pipefail

REPO_URL="https://github.com/mohit-0204/android-kmp-ai-skills"
REPO_RAW="https://raw.githubusercontent.com/mohit-0204/android-kmp-ai-skills/main"
SKILLS=()  # populated dynamically from skills/ directory after source is resolved

AGENT_DIRS=(
    "$HOME/.gemini/antigravity/skills"
    "$HOME/.gemini/skills"
    "$HOME/.cursor/skills"
    "$HOME/.codex/skills"
    "$HOME/.continue/skills"
)

PROJECT_LOCAL_DIR=".agents/skills"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${BLUE}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✅${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠️${NC}  $*"; }
error()   { echo -e "${RED}❌${NC} $*" >&2; }
header()  { echo -e "\n${BOLD}${CYAN}$*${NC}"; }

PROJECT_MODE=false
for arg in "$@"; do
    case $arg in
        --project)       PROJECT_MODE=true ;;
        --help|-h)
            echo "Usage: install.sh [--project]"
            echo "  --project   Install into current project (.agents/skills/)"
            exit 0 ;;
    esac
done

# Detect if running from a local clone or via curl
SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && "${BASH_SOURCE[0]}" != "bash" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# Detect Python 3
PYTHON=""
for py in python3 python; do
    if command -v "$py" &>/dev/null; then
        if "$py" -c "import sys; assert sys.version_info[0]==3" 2>/dev/null; then
            PYTHON="$py"; break
        fi
    fi
done
[[ -z "$PYTHON" ]] && { error "Python 3 required. Please install it first."; exit 1; }

# ── Detect agents ──────────────────────────────────────────────────────────────
header "🔍 Detecting AI agents..."
DETECTED_AGENTS=()
for dir in "${AGENT_DIRS[@]}"; do
    if [[ -d "$(dirname "$dir")" ]]; then
        DETECTED_AGENTS+=("$dir")
        success "$(basename "$(dirname "$dir")"): $dir"
    fi
done
if [[ "$PROJECT_MODE" == "true" ]]; then
    LOCAL_PATH="$(pwd)/$PROJECT_LOCAL_DIR"
    DETECTED_AGENTS+=("$LOCAL_PATH")
    info "Project-local: $LOCAL_PATH"
fi
[[ ${#DETECTED_AGENTS[@]} -eq 0 ]] && { error "No AI agents found."; exit 1; }

# ── Download skills ────────────────────────────────────────────────────────────
header "📦 Preparing skill files..."
TMPDIR_PATH=""
SKILLS_SOURCE=""
if [[ -n "$SCRIPT_DIR" && -d "$SCRIPT_DIR/skills" ]]; then
    SKILLS_SOURCE="$SCRIPT_DIR/skills"
    info "Using local repo at $SKILLS_SOURCE"
else
    TMPDIR_PATH="$(mktemp -d)"
    info "Downloading from GitHub..."
    if command -v git &>/dev/null; then
        git clone --depth=1 --quiet "$REPO_URL" "$TMPDIR_PATH/repo"
        SKILLS_SOURCE="$TMPDIR_PATH/repo/skills"
    else
        curl -sSL "$REPO_URL/archive/main.tar.gz" | tar -xz -C "$TMPDIR_PATH"
        SKILLS_SOURCE="$TMPDIR_PATH/android-kmp-ai-skills-main/skills"
    fi
    success "Downloaded."
fi

# Populate SKILLS dynamically from whatever is in skills/ directory
mapfile -t SKILLS < <(ls -1 "$SKILLS_SOURCE" 2>/dev/null)
info "Found ${#SKILLS[@]} skill(s) to install."
# ── Install skills ─────────────────────────────────────────────────────────────
header "📂 Installing ${#SKILLS[@]} skills..."
for skill in "${SKILLS[@]}"; do
    skill_src="$SKILLS_SOURCE/$skill"
    [[ ! -d "$skill_src" ]] && { warn "Skill '$skill' not found. Skipping."; continue; }
    for agent_dir in "${DETECTED_AGENTS[@]}"; do
        target="$agent_dir/$skill"
        mkdir -p "$target"
        # Exclude workspace.json — it will be generated locally
        if command -v rsync &>/dev/null; then
            rsync -a --exclude="workspace.json" "$skill_src/" "$target/"
        else
            cp -r "$skill_src/." "$target/"
            rm -f "$target/workspace.json"
        fi
        success "'$skill' → $target"
    done
done

# ── Official skills via android CLI ───────────────────────────────────────────
header "🤖 Installing official Android/KMP skills..."
if command -v android &>/dev/null; then
    android skills add --all
    success "Official skills installed."
else
    warn "'android' CLI not found — skipping official skills."
    info "Get it from: https://developer.android.com/tools/android-cli"
fi

# ── Generate workspace.json ────────────────────────────────────────────────────
header "⚙️  Generating workspace.json..."
SETUP_SCRIPT=""
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/tools/setup_workspace.py" ]]; then
    SETUP_SCRIPT="$SCRIPT_DIR/tools/setup_workspace.py"
else
    SETUP_SCRIPT="${TMPDIR_PATH}/setup_workspace.py"
    curl -sSL "$REPO_RAW/tools/setup_workspace.py" -o "$SETUP_SCRIPT"
fi

for agent_dir in "${DETECTED_AGENTS[@]}"; do
    skill_dir="$agent_dir/android-emulator-qa"
    [[ ! -d "$skill_dir" ]] && continue
    "$PYTHON" "$SETUP_SCRIPT" --skill-dir "$skill_dir"
done

# ── Update .gitignore ─────────────────────────────────────────────────────────
if [[ "$PROJECT_MODE" == "true" ]]; then
    header "📝 Updating .gitignore..."
    GITIGNORE="$(pwd)/.gitignore"
    ENTRY=".agents/skills/"
    if [[ -f "$GITIGNORE" ]] && grep -qxF "$ENTRY" "$GITIGNORE"; then
        info ".gitignore already has '$ENTRY'"
    else
        { echo ""; echo "# AI agent skills (machine-specific, not for version control)"; echo "$ENTRY"; } >> "$GITIGNORE"
        success "Added '$ENTRY' to .gitignore"
    fi
fi

# ── Cleanup ───────────────────────────────────────────────────────────────────
[[ -n "$TMPDIR_PATH" ]] && rm -rf "$TMPDIR_PATH"

# ── Summary ───────────────────────────────────────────────────────────────────
header "🎉 Done!"
echo ""
echo -e "  Installed ${#SKILLS[@]} skill(s) for ${#DETECTED_AGENTS[@]} agent(s)."
if [[ "$PROJECT_MODE" == "true" ]]; then
    echo -e "  Mode: ${YELLOW}Project-local${NC} — $(pwd)/.agents/skills/"
else
    echo -e "  Mode: ${GREEN}Global${NC}"
fi
echo ""
echo -e "  ${BOLD}Tip:${NC} Edit workspace.json if auto-detection missed anything."
echo ""
