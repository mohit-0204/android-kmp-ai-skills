#!/usr/bin/env python3
"""
install_and_launch.py — One-shot: build, install, and launch an Android/KMP app.

Auto-detects the project type (Android vs KMP) from the project directory structure.
Reads workspace.json only for SDK tool paths (adb).

Usage:
    python3 install_and_launch.py --project <project_path> --serial <device_serial>
    python3 install_and_launch.py --project /path/to/MyProject --serial emulator-5554
    python3 install_and_launch.py --project /path/to/MyProject --serial emulator-5554 --module composeApp
    python3 install_and_launch.py --project /path/to/MyProject --serial emulator-5554 --variant Release

Options:
    --project   Path to the root of the Android/KMP project (required)
    --serial    ADB device serial (required)
    --module    Gradle module to build (auto-detected if not specified)
    --variant   Build variant (default: Debug)
    --package   Override package name (auto-detected from device after install)
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parent.parent


def load_sdk_config() -> dict:
    """Load SDK paths from workspace.json if present."""
    config_path = SKILL_DIR / "workspace.json"
    if config_path.exists():
        try:
            with config_path.open(encoding="utf-8") as f:
                return json.load(f).get("sdk", {})
        except Exception:
            pass
    return {}


def run(cmd: list[str], cwd: Path | None = None, stream: bool = False) -> subprocess.CompletedProcess | None:
    print(f"\n▶ {' '.join(cmd)}", flush=True)
    if stream:
        proc = subprocess.Popen(cmd, cwd=cwd, stdout=sys.stdout, stderr=sys.stderr, text=True)
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed with exit code {proc.returncode}")
        return None
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result


def detect_module(project_path: Path) -> str:
    """Detect Gradle module from project directory structure."""
    if (project_path / "composeApp").exists():
        return "composeApp"
    if (project_path / "androidApp").exists():
        return "androidApp"
    if (project_path / "app").exists():
        return "app"
    raise RuntimeError(
        f"Cannot auto-detect module for '{project_path.name}'. Use --module."
    )


def find_package_on_device(adb: str, serial: str, keyword: str) -> str | None:
    result = subprocess.run(
        [adb, "-s", serial, "shell", "pm", "list", "packages"],
        capture_output=True, text=True, timeout=10
    )
    for line in result.stdout.splitlines():
        pkg = line.replace("package:", "").strip()
        if keyword.lower() in pkg.lower():
            return pkg
    return None


def resolve_activity(adb: str, serial: str, package: str) -> str | None:
    result = subprocess.run(
        [adb, "-s", serial, "shell", "cmd", "package", "resolve-activity", "--brief", package],
        capture_output=True, text=True, timeout=10
    )
    for line in result.stdout.splitlines():
        if "/" in line:
            return line.strip()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build, install, and launch an Android/KMP app.")
    parser.add_argument("--project", required=True, help="Path to project root")
    parser.add_argument("--serial", required=True, help="ADB device serial")
    parser.add_argument("--module", help="Gradle module (auto-detected if not specified)")
    parser.add_argument("--variant", default="Debug", help="Build variant (default: Debug)")
    parser.add_argument("--package", help="Package name override (auto-detected from device)")
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    if not project_path.exists():
        print(f"error: project path does not exist: {project_path}", file=sys.stderr)
        return 1

    # Use adb from workspace.json SDK config if available, else fall back to PATH
    sdk = load_sdk_config()
    adb = sdk.get("adb") or "adb"

    # Detect module
    try:
        module = args.module or detect_module(project_path)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    gradle_task = f":{module}:install{args.variant}"
    print(f"\n{'='*50}")
    print(f"Project : {project_path}")
    print(f"Serial  : {args.serial}")
    print(f"Task    : {gradle_task}")
    print(f"{'='*50}\n")

    # Build & install
    try:
        run(["./gradlew", gradle_task, "--console=plain", "--quiet"],
            cwd=project_path, stream=True)
    except RuntimeError:
        print("\nerror: Build/install failed. Run with --info for details.", file=sys.stderr)
        return 1

    print("\n✅ Install successful.", flush=True)

    # Resolve package name from device
    package = args.package
    if not package:
        keyword = project_path.name.lower().replace("-", "").replace("_", "").replace(" ", "")
        package = find_package_on_device(adb, args.serial, keyword)
        if not package:
            print("⚠️  Could not auto-detect package. Use --package.", file=sys.stderr)
            return 1
        print(f"📦 Detected package: {package}", flush=True)

    # Resolve activity
    activity_str = resolve_activity(adb, args.serial, package)
    if not activity_str:
        print(f"⚠️  Could not resolve activity for {package}.", file=sys.stderr)
        return 1
    print(f"🎯 Activity: {activity_str}", flush=True)

    # Force-stop then launch
    subprocess.run([adb, "-s", args.serial, "shell", "am", "force-stop", package],
                   capture_output=True)
    run([adb, "-s", args.serial, "shell", "am", "start", "-n", activity_str])

    print(f"\n🚀 App launched: {package}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
