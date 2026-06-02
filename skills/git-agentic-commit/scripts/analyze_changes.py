"""
analyze_changes.py — Smart Atomic Commit Analyzer
===================================================
Mode A (Plan-Aware):  Reads PHASED_IMPLEMENTATION_PLAN.md (or similar).
                      Groups files by phase using artifact names from each
                      phase body. Enforces phase ordering. Co-groups tests
                      and migrations with their parent phase.

Mode B (Semantic):    No plan file present. Groups files by package / feature
                      cluster using import graph and naming conventions.
                      Still co-groups tests, migrations, and config with code.

Usage:
    python3 analyze_changes.py          # run from project root
    python3 analyze_changes.py --debug  # show keyword/artifact matching detail
"""

import subprocess
import os
import re
import sys
from collections import defaultdict

DEBUG = "--debug" in sys.argv

# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def run(cmd, cwd=None):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.stdout.strip()


def get_changed_files():
    """
    Returns a list of dicts: {path, status, category}
    Expands untracked directories to individual files.
    """
    lines = run(["git", "status", "--porcelain"]).split("\n")
    files = []
    for line in lines:
        if not line.strip():
            continue
        status = line[:2].strip()
        raw_path = line[3:].strip()

        if raw_path.endswith("/"):
            # Untracked directory — expand
            dir_files = run(["find", raw_path.rstrip("/"), "-type", "f"]).split("\n")
            for df in dir_files:
                df = df.strip()
                if df:
                    files.append({"path": df, "status": "??"})
        else:
            files.append({"path": raw_path, "status": status})

    valid_files = []
    for f in files:
        if "reference_docs/" in f["path"]:
            continue
            
        f["category"] = _categorize(f["path"])
        # Normalise paths that git --porcelain strips the leading dot from
        # e.g. git returns ".gitignore" but find/open needs the real path
        if not os.path.exists(f["path"]) and os.path.exists("." + f["path"]):
            f["path"] = "." + f["path"]
            f["category"] = _categorize(f["path"])
        valid_files.append(f)

    return valid_files


def _categorize(path):
    p = path.lower()
    if "test" in p:
        return "test"
    if p.endswith((".sql",)):
        return "migration"
    if "pom.xml" in p or "build.gradle" in p or "build.gradle.kts" in p:
        return "build"
    if p.endswith((".properties", ".yml", ".yaml", ".env", ".toml")):
        return "config"
    if p.endswith((".md", ".txt", ".rst", ".adoc")):
        return "docs"
    if p.endswith((".java", ".kt", ".py", ".js", ".ts", ".go", ".rs", ".swift")):
        return "src"
    return "other"


def get_diff_text(filepath):
    # Use HEAD to include both staged and unstaged changes in the diff
    return run(["git", "diff", "HEAD", "--", filepath])


def get_file_content(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", errors="replace") as fh:
                return fh.read()
        except Exception:
            return ""
    return ""

# ---------------------------------------------------------------------------
# Plan parsing
# ---------------------------------------------------------------------------

PLAN_CANDIDATES = [
    "reference_docs/PHASED_IMPLEMENTATION_PLAN.md",
    "PHASED_IMPLEMENTATION_PLAN.md",
    "ROADMAP.md",
    "IMPLEMENTATION_PLAN.md",
    "PLAN.md",
    "docs/PLAN.md",
]


def find_plan():
    for candidate in PLAN_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


def parse_phases(plan_text):
    """
    Returns a list of dicts ordered by phase number:
      {number, title, body, artifacts}

    Artifacts are PascalCase class names and snake_case SQL file names found
    in the phase body — these are the most reliable match signals.
    """
    # Split on level-2 headings (## N. Phase ...)
    raw_sections = re.split(r"\n(?=##\s)", plan_text)
    phases = []

    for section in raw_sections:
        # Match e.g. "## 5. Phase 1: Add Query Tracking Table"
        m = re.match(r"##\s+(\d+)\.\s+(Phase\s+\d+[^\n]*)", section, re.IGNORECASE)
        if not m:
            continue
        section_num = int(m.group(1))
        title = m.group(2).strip()
        body = section[m.end():].strip()

        # Extract artifact signals from body
        # 1. PascalCase class names (likely Java/Kotlin classes)
        class_names = set(re.findall(r"\b([A-Z][a-zA-Z0-9]{3,})\b", body))
        # 2. SQL migration file names  e.g. V7__add_search_queries.sql
        sql_files = set(re.findall(r"\b(V\d+__[\w]+\.sql)\b", body))
        # 3. Package segments  e.g. cache, ingestion, docs
        pkg_segments = set(re.findall(r"`([a-z][a-z0-9_/]+)`", body))

        artifacts = class_names | sql_files | pkg_segments

        if DEBUG:
            print(f"[DEBUG] Phase section {section_num}: {title}")
            print(f"        artifacts: {artifacts}\n")

        phases.append({
            "number": section_num,
            "title": title,
            "body": body,
            "artifacts": artifacts,
        })

    # Sort by the PHASE digit in the title (e.g. "Phase 1"), not the section number.
    # The section number (## 5.) is just position in the doc; the phase digit is semantic order.
    def _phase_digit(p):
        m = re.search(r"Phase\s+(\d+)", p["title"], re.IGNORECASE)
        return int(m.group(1)) if m else p["number"]

    for p in phases:
        p["phase_digit"] = _phase_digit(p)

    phases.sort(key=lambda p: p["phase_digit"])
    return phases


def score_file_for_phase(filepath, file_content, phase):
    """
    Returns a relevance score (int).  Higher = better match for this phase.
    """
    score = 0
    basename = os.path.basename(filepath)
    name_no_ext = os.path.splitext(basename)[0]
    path_lower = filepath.lower()

    for artifact in phase["artifacts"]:
        art_lower = artifact.lower()
        # Direct file name match  (highest weight)
        if artifact == basename or artifact == name_no_ext:
            score += 20
        # File name contains artifact (e.g. SearchQueryEntity.java contains 'SearchQuery')
        elif art_lower in basename.lower():
            score += 10
        # Path contains artifact (e.g. /cache/ matches 'cache')
        elif art_lower in path_lower:
            score += 6
        # File content references artifact
        elif len(artifact) > 4 and artifact in file_content:
            score += 2

    return score

# ---------------------------------------------------------------------------
# Grouping — Plan-Aware Mode
# ---------------------------------------------------------------------------

def group_by_plan(files, phases):
    """
    Assigns each file to exactly one phase group.
    Uses the highest-scoring phase. Ties go to the earlier phase.
    After initial assignment, co-groups:
      - Tests → same group as the source file they test
      - Migrations → same group as the entity/repo that consumes the migration
      - Build/config → earliest phase that has any scored match
    """
    # Load content once
    for f in files:
        f["content"] = get_file_content(f["path"]) + "\n" + get_diff_text(f["path"])

    # Phase index: phase_digit → group list  (phase_digit = the "N" in "Phase N")
    phase_groups = {p["phase_digit"]: {"phase": p, "files": []} for p in phases}
    unassigned = []

    # First pass: score every non-test, non-migration, non-build, non-config file
    src_files = [f for f in files if f["category"] in ("src", "docs", "other")]
    secondary_files = [f for f in files if f["category"] in ("test", "migration", "build", "config")]

    def assign_to_best_phase(f):
        best_phase_digit = None
        best_score = 0
        for phase in phases:  # already sorted by phase_digit (ascending)
            s = score_file_for_phase(f["path"], f["content"], phase)
            if DEBUG:
                print(f"[DEBUG] {f['path']} vs Phase {phase['phase_digit']}: score={s}")
            if s > best_score:
                best_score = s
                best_phase_digit = phase["phase_digit"]
        return best_phase_digit, best_score

    # Assign src/docs/other files
    for f in src_files:
        num, score = assign_to_best_phase(f)
        if num is not None and score > 0:
            phase_groups[num]["files"].append(f["path"])
        else:
            unassigned.append(f)

    # Co-group tests with their corresponding source files
    for f in [x for x in secondary_files if x["category"] == "test"]:
        base = os.path.splitext(os.path.basename(f["path"]))[0]
        # Remove common test suffixes to get the source class name
        source_class = re.sub(r"Test$", "", base)
        placed = False
        for num, group in phase_groups.items():
            for gf in group["files"]:
                if source_class in os.path.basename(gf):
                    group["files"].append(f["path"])
                    placed = True
                    break
            if placed:
                break
        if not placed:
            # Fall back to scoring
            num, score = assign_to_best_phase(f)
            if num is not None and score > 0:
                phase_groups[num]["files"].append(f["path"])
            else:
                unassigned.append(f)

    # Co-group migrations with the phase whose entity references it
    # or by scoring the migration body itself
    for f in [x for x in secondary_files if x["category"] == "migration"]:
        num, score = assign_to_best_phase(f)
        # Also try to match the SQL filename to phase artifacts directly
        if score == 0:
            basename = os.path.basename(f["path"])
            for phase in phases:
                if basename in phase["artifacts"]:
                    num = phase["phase_digit"]
                    break
        if num is not None:
            phase_groups[num]["files"].append(f["path"])
        else:
            unassigned.append(f)

    # Co-group build/config with the earliest phase that has a scored match
    for f in [x for x in secondary_files if x["category"] in ("build", "config")]:
        scored_phases = []
        for phase in phases:  # already sorted by phase_digit ascending
            s = score_file_for_phase(f["path"], f["content"], phase)
            if s > 0:
                scored_phases.append((phase["phase_digit"], s))
        if scored_phases:
            # Assign to earliest phase (lowest phase_digit) that matches
            earliest = min(scored_phases, key=lambda x: x[0])[0]
            phase_groups[earliest]["files"].append(f["path"])
        else:
            unassigned.append(f)

    # Build ordered result (sorted by phase_digit), skip empty phases
    groups = []
    for phase in phases:  # already sorted by phase_digit
        pg = phase_groups[phase["phase_digit"]]
        if pg["files"]:
            groups.append({
                "phase_number": phase["phase_digit"],
                "phase_title": phase["title"],
                "files": pg["files"],
                "mode": "plan",
            })

    # Leftovers become their own semantic groups
    if unassigned:
        semantic = group_semantically(unassigned)
        for g in semantic:
            g["mode"] = "semantic-fallback"
        groups.extend(semantic)

    return groups

# ---------------------------------------------------------------------------
# Grouping — Semantic-Only Mode  (no plan)
# ---------------------------------------------------------------------------

def group_semantically(files):
    """
    Groups files using:
    1. Package/directory clustering  (files in the same package belong together)
    2. Test-source pairing by name
    3. Migration-entity pairing by table/class name in file content
    4. Build/config attached to the earliest feature group that imports from them
    """
    # Load content if not already loaded
    for f in files:
        if "content" not in f:
            f["content"] = get_file_content(f["path"]) + "\n" + get_diff_text(f["path"])

    src_files = [f for f in files if f["category"] == "src"]
    test_files = [f for f in files if f["category"] == "test"]
    migration_files = [f for f in files if f["category"] == "migration"]
    build_files = [f for f in files if f["category"] == "build"]
    config_files = [f for f in files if f["category"] == "config"]
    other_files = [f for f in files if f["category"] in ("docs", "other")]

    # Cluster src files by their immediate package directory
    pkg_clusters = defaultdict(list)
    for f in src_files:
        # Use the parent directory as the cluster key
        pkg_dir = os.path.dirname(f["path"])
        pkg_clusters[pkg_dir].append(f)

    groups = []
    used = set()

    for pkg_dir, cluster_files in pkg_clusters.items():
        group_paths = [f["path"] for f in cluster_files]
        used.update(group_paths)

        # Infer a label from the package dir
        pkg_name = os.path.basename(pkg_dir)
        if not pkg_name:
            pkg_name = "core"

        # Co-group tests that match any file in this cluster
        for tf in test_files:
            base = os.path.splitext(os.path.basename(tf["path"]))[0]
            source_class = re.sub(r"Test$", "", base)
            if any(source_class in os.path.basename(gf) for gf in group_paths):
                if tf["path"] not in used:
                    group_paths.append(tf["path"])
                    used.add(tf["path"])

        # Co-group migrations that reference the same class/table names
        cluster_keywords = set()
        for cf in cluster_files:
            # Pull class names from file content
            cluster_keywords.update(re.findall(r"\b([A-Z][a-zA-Z0-9]{3,})\b", cf["content"]))

        for mf in migration_files:
            if mf["path"] in used:
                continue
            mig_text = mf["content"].lower()
            if any(kw.lower() in mig_text for kw in cluster_keywords if len(kw) > 5):
                group_paths.append(mf["path"])
                used.add(mf["path"])

        # Co-group config/build that import/reference this package's classes
        for bf in build_files + config_files:
            if bf["path"] in used:
                continue
            bf_text = bf["content"]
            if any(kw in bf_text for kw in cluster_keywords if len(kw) > 5):
                group_paths.append(bf["path"])
                used.add(bf["path"])

        groups.append({
            "phase_number": None,
            "phase_title": f"Feature: {pkg_name}",
            "files": group_paths,
            "mode": "semantic",
        })

    # Remaining tests not yet placed
    for tf in [t for t in test_files if t["path"] not in used]:
        groups.append({
            "phase_number": None,
            "phase_title": f"Tests: {os.path.basename(tf['path'])}",
            "files": [tf["path"]],
            "mode": "semantic",
        })
        used.add(tf["path"])

    # Remaining migrations
    for mf in [m for m in migration_files if m["path"] not in used]:
        groups.append({
            "phase_number": None,
            "phase_title": f"Schema: {os.path.basename(mf['path'])}",
            "files": [mf["path"]],
            "mode": "semantic",
        })
        used.add(mf["path"])

    # Standalone docs
    for df in other_files:
        if df["path"] not in used:
            groups.append({
                "phase_number": None,
                "phase_title": f"Docs: {os.path.basename(df['path'])}",
                "files": [df["path"]],
                "mode": "semantic",
            })
            used.add(df["path"])

    # Anything still unplaced (build/config with no source match)
    remaining = [f["path"] for f in files if f["path"] not in used]
    if remaining:
        groups.append({
            "phase_number": None,
            "phase_title": "Build & Config",
            "files": remaining,
            "mode": "semantic",
        })

    return groups


# ---------------------------------------------------------------------------
# Dependency Resolution (Auto-Grouping)
# ---------------------------------------------------------------------------

def enforce_dependencies(groups):
    """
    Scans file contents to build a dependency graph (e.g. File A uses Class B).
    If a file depends on another file that is scheduled for a LATER commit,
    it pulls the dependency down into its own commit to ensure atomic builds.
    """
    changed = True
    # Prevent infinite loops in case of bizarre circular/overlapping matching
    max_iters = 10
    iters = 0

    while changed and iters < max_iters:
        changed = False
        iters += 1

        # Build map of identifiable tokens (class names) -> (group_idx, filepath)
        token_map = {}
        for g_idx, group in enumerate(groups):
            for f in group["files"]:
                basename = os.path.basename(f)
                name_no_ext = os.path.splitext(basename)[0]
                if len(name_no_ext) > 3 and _categorize(f) in ("src", "migration", "config"):
                    token_map[name_no_ext] = (g_idx, f)

        # Check dependencies
        for g_idx, group in enumerate(groups):
            for f in list(group["files"]):  # copy list because we might mutate other groups
                # Skip parsing huge or binary files
                if _categorize(f) not in ("src", "test", "config"):
                    continue
                
                content = get_file_content(f)
                if not content:
                    continue

                for token, (dep_g_idx, dep_f) in token_map.items():
                    if dep_g_idx > g_idx and f != dep_f:
                        # Dependency is in a later group
                        if token in content:
                            if DEBUG:
                                print(f"[DEBUG] Auto-Pull: '{os.path.basename(f)}' (Commit {g_idx+1}) needs '{token}'. Moving '{os.path.basename(dep_f)}' from Commit {dep_g_idx+1}.")
                            
                            # Move it to the earlier group
                            groups[dep_g_idx]["files"].remove(dep_f)
                            group["files"].append(dep_f)
                            
                            # Update token map so we don't pull it again incorrectly
                            token_map[token] = (g_idx, dep_f)
                            changed = True

    # Cleanup empty groups
    return [g for g in groups if g["files"]]

# ---------------------------------------------------------------------------
# Commit message generation
# ---------------------------------------------------------------------------

def infer_commit_type(files):
    """Picks the conventional commit type based on what's in the group."""
    cats = {_categorize(f) for f in files}
    if cats == {"test"}:
        return "test"
    if cats == {"migration"}:
        return "feat"
    if cats <= {"docs", "other"}:
        return "docs"
    if cats <= {"config", "build", "other"}:
        return "build"
    if "src" in cats:
        return "feat"
    return "chore"


def infer_scope(files, phase_title=None):
    """
    Derives a short domain scope token — matching the user's commit style:
    single lowercase noun like 'cache', 'ingestion', 'auth', 'backend', 'core'.
    """
    # 1. Dominant source package directory (most reliable)
    pkg_dirs = [os.path.dirname(f) for f in files if _categorize(f) == "src"]
    if pkg_dirs:
        counts = defaultdict(int)
        for d in pkg_dirs:
            seg = os.path.basename(d)
            if seg and "." not in seg:
                counts[seg] += 1
        if counts:
            return max(counts, key=counts.get)

    # 2. Fall back to clean word from phase_title (plan mode)
    if phase_title:
        stripped = re.sub(
            r"^(Phase\s+\d+|Feature|Docs|Tests|Schema|Build\s*&\s*Config)\s*[:\-]\s*",
            "",
            phase_title,
            flags=re.IGNORECASE,
        ).strip().rstrip(":. ")
        words = stripped.split()
        stop = {"add", "the", "and", "for", "with", "from", "into", "that",
                "as", "a", "an", "use", "make", "its", "or", "of", "to"}
        scope_words = [
            w.lower() for w in words
            if w.lower() not in stop
            and 2 < len(w) <= 20
            and "." not in w
            and "/" not in w
        ]
        if scope_words:
            return scope_words[0]

    # 3. Last resort based on file category
    if files:
        cat = _categorize(files[0])
        return {"test": "test", "migration": "schema", "docs": "docs",
                "build": "build", "config": "config"}.get(cat, "core")

    return "core"


def generate_commit_subject(group):
    """
    Generates the subject line in the user's style:
      type(scope): lowercase imperative description

    Rules observed from commit history:
    - Description starts with lowercase ('implement', 'add', etc.)
    - No 'phase N -' prefix — describe the capability delivered based on files
    - Scope is the domain package: cache, ingestion, auth, backend, core
    - 'feat' for most work, 'chore' only for housekeeping/init, 'docs' for docs-only
    """
    files = group["files"]
    phase_title = group.get("phase_title", "")

    commit_type = infer_commit_type(files)
    scope = infer_scope(files, phase_title)

    # Always use semantic generation to tell what was *actually* done
    src_names = [
        os.path.splitext(os.path.basename(f))[0]
        for f in files if _categorize(f) == "src"
    ]
    migration_names = [os.path.basename(f) for f in files if _categorize(f) == "migration"]
    doc_names = [os.path.basename(f) for f in files if _categorize(f) == "docs"]

    if src_names:
        if len(src_names) == 1:
            description = f"implement {_pascal_to_words(src_names[0])}"
        else:
            # Summarise the cluster — e.g. "implement cache layer"
            key_classes = src_names[:3]
            readable = [_pascal_to_words(n) for n in key_classes]
            if len(src_names) > 3:
                description = f"implement {scope} layer"
            elif len(readable) == 1:
                description = f"implement {readable[0]}"
            else:
                joined = ", ".join(readable[:-1]) + f" and {readable[-1]}"
                description = f"implement {joined}"
    elif migration_names:
        table = _migration_to_table(migration_names[0])
        description = f"add {table} schema migration"
    elif doc_names:
        description = f"update {', '.join(doc_names)}"
    else:
        description = f"update {scope} configuration"

    return f"{commit_type}({scope}): {description}"


def generate_commit_body(group):
    """
    Generates a bullet-list commit body matching the user's style:
      - Verb Noun ... (sentence case, no trailing period)

    Bullets are derived from the files in the group — each meaningful
    source file or migration gets one bullet describing what it introduces.
    """
    files = group["files"]
    phase_title = group.get("phase_title", "")
    bullets = []

    src_files = [f for f in files if _categorize(f) == "src"]
    test_files = [f for f in files if _categorize(f) == "test"]
    migration_files = [f for f in files if _categorize(f) == "migration"]
    config_files = [f for f in files if _categorize(f) in ("config", "build")]
    doc_files = [f for f in files if _categorize(f) == "docs"]

    for f in src_files:
        basename = os.path.basename(f)
        name = os.path.splitext(basename)[0]
        words = _pascal_to_words(name)
        # Guess the verb from the class name suffix
        if name.endswith("Service"):
            bullets.append(f"Introduce {words} to handle {_scope_from_path(f)} business logic")
        elif name.endswith("Controller"):
            bullets.append(f"Add {words} with REST endpoints for {_scope_from_path(f)}")
        elif name.endswith("Repository"):
            bullets.append(f"Add {words} for database access")
        elif name.endswith("Entity"):
            bullets.append(f"Define {words} as the JPA persistence model")
        elif name.endswith(("Normalizer", "Mapper")):
            bullets.append(f"Implement {words} for consistent data transformation")
        elif name.endswith("Properties"):
            bullets.append(f"Bind {words} from application configuration")
        elif name.endswith("Config"):
            bullets.append(f"Configure {words} for Spring context setup")
        elif name.endswith(("Result", "Response", "Request", "Dto", "DTO")):
            bullets.append(f"Define {words} as the data transfer model")
        elif name.endswith("Status"):
            bullets.append(f"Introduce {words} enum for state tracking")
        else:
            bullets.append(f"Implement {words} ({basename})")

    if migration_files:
        for f in migration_files:
            table = _migration_to_table(os.path.basename(f))
            bullets.append(f"Add Flyway migration to create {table}")

    if test_files:
        test_names = [os.path.splitext(os.path.basename(f))[0] for f in test_files]
        if len(test_names) == 1:
            bullets.append(f"Add unit tests for {_pascal_to_words(test_names[0].replace('Test', ''))}")
        else:
            bullets.append(f"Add unit and integration tests for {_scope_from_path(test_files[0])} layer")

    if config_files:
        for f in config_files:
            basename = os.path.basename(f)
            diff = get_diff_text(f)
            
            if basename == "pom.xml" or basename == "build.gradle":
                added_deps = re.findall(r"^\+\s*<artifactId>([^<]+)</artifactId>", diff, re.MULTILINE)
                if not added_deps: # Gradle fallback
                    added_deps = re.findall(r"^\+\s*(?:implementation|api|testImplementation)\s+['\"]([^'\":]+:[^'\":]+)", diff, re.MULTILINE)
                    
                if added_deps:
                    deps_str = ", ".join(added_deps[:3])
                    if len(added_deps) > 3:
                        deps_str += ", etc."
                    bullets.append(f"Add required dependencies ({deps_str}) to {basename}")
                else:
                    bullets.append(f"Add required dependencies to {basename}")
                    
            elif basename.endswith(".properties") or basename.endswith(".yml"):
                added_props = re.findall(r"^\+\s*([a-zA-Z0-9.-]+)=", diff, re.MULTILINE)
                if added_props:
                    prefixes = sorted({p.split('.')[0] for p in added_props if '.' in p})
                    if prefixes:
                        bullets.append(f"Update {basename} with new configuration properties ({', '.join(prefixes)}.*)")
                    else:
                        bullets.append(f"Update {basename} with new configuration properties")
                else:
                    bullets.append(f"Update {basename} with new configuration properties")
            else:
                bullets.append(f"Update {basename} configuration")

    if doc_files:
        for f in doc_files:
            bullets.append(f"Update {os.path.basename(f)} with latest implementation notes")

    return bullets


# ---------------------------------------------------------------------------
# String helpers
# ---------------------------------------------------------------------------

def _to_sentence_case(text):
    """Capitalise the first character; leave the rest as-is."""
    text = text.strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def _pascal_to_words(name):
    """CacheOrchestratorService → cache orchestrator service"""
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return words.lower().strip()


def _scope_from_path(filepath):
    """Extract the last meaningful package segment from a file path."""
    return os.path.basename(os.path.dirname(filepath))


def _migration_to_table(filename):
    """V7__add_search_queries.sql → 'search_queries' table"""
    m = re.search(r"V\d+__(.+)\.sql", filename, re.IGNORECASE)
    if m:
        return m.group(1).replace("_", " ").replace("add ", "").strip()
    return filename


def _extract_phase_digit(title):
    m = re.search(r"Phase\s+(\d+)", title, re.IGNORECASE)
    return m.group(1) if m else "?"

# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_report(groups, plan_path):
    mode_label = f"Plan-Aware ({plan_path})" if plan_path else "Semantic-Only (no plan found)"
    print(f"# Smart Atomic Commit Suggestions \u2014 {mode_label}\n")
    print("=" * 70)

    for i, group in enumerate(groups, 1):
        subject = generate_commit_subject(group)
        body_bullets = generate_commit_body(group)
        mode_tag = f"[{group['mode']}]"
        phase_tag = f" (Phase {group['phase_number']})" if group["phase_number"] is not None else ""

        print(f"\n## Commit {i}{phase_tag}  {mode_tag}")
        print(f"   Files   :")
        for f in sorted(group["files"]):
            print(f"     git add \"{f}\"")

        print(f"\n   Commit message:")
        print(f"   \u250c\u2500 {subject}")
        if body_bullets:
            print(f"   \u2502")
            for bullet in body_bullets:
                print(f"   \u2502  - {bullet}")
        print(f"   \u2514\u2500")

        print(f"\n   Command:")
        if body_bullets:
            body_str = "\\n".join(f"- {b}" for b in body_bullets)
            print(f"     git commit -m \"{subject}\" -m \"{body_str}\"")
        else:
            print(f"     git commit -m \"{subject}\"")

    print("\n" + "=" * 70)
    print(f"\nTotal: {len(groups)} atomic commit(s) proposed.")
    if "--execute" not in sys.argv:
        print("\nNOTE: Run with --execute to automatically stash, build, and commit these groups sequentially.")
        print("      Otherwise, verify build independently for each commit before pushing.")
        print("      Run: mvn compile  (Java)  or  ./gradlew assemble  (Android/KMP)")


def execute_commits(groups):
    print("\n" + "=" * 70)
    print("🚀 EXECUTING STASH-AND-BUILD WORKFLOW")
    print("=" * 70)

    # Detect build command
    build_cmd = None
    if os.path.exists("pom.xml") or os.path.exists("mvnw"):
        build_cmd = ["./mvnw", "compile"] if os.path.exists("mvnw") else ["mvn", "compile"]
    elif os.path.exists("build.gradle") or os.path.exists("build.gradle.kts") or os.path.exists("gradlew"):
        build_cmd = ["./gradlew", "assemble"] if os.path.exists("gradlew") else ["gradle", "assemble"]
    else:
        print("[WARN] No pom.xml or build.gradle found. Skipping build verification.")

    # Unstage anything currently staged to avoid accidental inclusions
    run(["git", "reset"])

    for i, group in enumerate(groups, 1):
        subject = generate_commit_subject(group)
        bullets = generate_commit_body(group)
        files = group["files"]

        print(f"\n⏳ Processing Commit {i}/{len(groups)}: {subject}")

        # 1. Add files
        for f in files:
            run(["git", "add", f])

        # 2. Stash everything else (keeping index intact in working tree)
        stash_out = run(["git", "stash", "push", "--keep-index", "--include-untracked", "-m", "git-agentic-commit temp"])
        stashed = "No local changes to save" not in stash_out

        # 3. Build verification
        build_passed = True
        if build_cmd:
            print(f"   ⚙️  Running build: {' '.join(build_cmd)} ...")
            # Run build interactively so user sees progress
            build_res = subprocess.run(build_cmd)
            if build_res.returncode != 0:
                print(f"   ❌ BUILD FAILED!")
                build_passed = False

        if not build_passed:
            if stashed:
                print("   🔄 Restoring stashed files...")
                run(["git", "stash", "pop"])
            print(f"\n🚨 Aborting execution due to build failure on Commit {i}.")
            print("   Please fix the build issue, stage the necessary files, and re-run.")
            return

        # 4. Commit
        print("   ✅ Build passed. Committing...")
        commit_args = ["git", "commit", "-m", subject]
        if bullets:
            body = "\n".join(f"- {b}" for b in bullets)
            commit_args.extend(["-m", body])
        run(commit_args)

        # 5. Restore stash
        if stashed:
            print("   🔄 Restoring remaining files...")
            run(["git", "stash", "pop"])

    print("\n🎉 All commits executed successfully!")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    files = get_changed_files()
    if not files:
        print("No changes detected. Working tree is clean.")
        return

    plan_path = find_plan()

    if plan_path:
        plan_text = get_file_content(plan_path)
        phases = parse_phases(plan_text)
        if phases:
            groups = group_by_plan(files, phases)
        else:
            # Plan file exists but has no parseable phases → semantic mode
            print(f"[WARN] Plan found at {plan_path} but no phases parsed. Using semantic mode.\n")
            groups = group_semantically(files)
    else:
        groups = group_semantically(files)

    groups = enforce_dependencies(groups)

    print_report(groups, plan_path)

    if "--execute" in sys.argv:
        execute_commits(groups)


if __name__ == "__main__":
    main()
