#!/usr/bin/env python3
"""
logcat_filter.py — Stream logcat for a specific package with color-coded log levels.

Usage:
    python3 logcat_filter.py --serial <device_serial> --package <package.name>
    python3 logcat_filter.py --serial emulator-5554 --package com.yourapp.debug
    python3 logcat_filter.py --package com.yourapp.debug          # uses first adb device
    python3 logcat_filter.py --package com.yourapp.debug --save   # also saves to /tmp/logcat_<timestamp>.txt

Features:
    - Filters logs to only the target package's PID
    - Color-codes: VERBOSE=white, DEBUG=cyan, INFO=green, WARN=yellow, ERROR=red, FATAL=red+bold
    - Saves output to /tmp/logcat_<timestamp>.txt when --save is used
    - Prints package PID at start so you can verify

NEW — Custom supplemental utility.
"""
import argparse
import subprocess
import sys
import os
from datetime import datetime


# ANSI color codes
COLORS = {
    "V": "\033[37m",       # white
    "D": "\033[36m",       # cyan
    "I": "\033[32m",       # green
    "W": "\033[33m",       # yellow
    "E": "\033[31m",       # red
    "F": "\033[1;31m",     # bold red
    "RESET": "\033[0m",
}


def get_pid(serial: str | None, package: str) -> str | None:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += ["shell", "pidof", "-s", package]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        pid = result.stdout.strip()
        return pid if pid else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def stream_logcat(serial: str | None, pid: str, save: bool):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += ["logcat", "--pid", pid]

    save_file = None
    if save:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"/tmp/logcat_{timestamp}.txt"
        save_file = open(save_path, "w", encoding="utf-8")
        print(f"[logcat_filter] Saving to {save_path}", flush=True)

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            # Detect log level from line format: "MM-DD HH:MM:SS PID TID LEVEL TAG: msg"
            parts = line.split()
            level = parts[4] if len(parts) > 4 else "V"
            color = COLORS.get(level, COLORS["V"])
            print(f"{color}{line.rstrip()}{COLORS['RESET']}", flush=True)
            if save_file:
                save_file.write(line)
    except KeyboardInterrupt:
        print("\n[logcat_filter] Stopped by user.", flush=True)
    finally:
        if save_file:
            save_file.close()
            print(f"[logcat_filter] Logcat saved.", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Stream color-coded logcat for a package.")
    parser.add_argument("--serial", "-s", help="ADB device serial (optional if only one device)")
    parser.add_argument("--package", "-p", required=True, help="Package name to filter")
    parser.add_argument("--save", action="store_true", help="Also save output to /tmp/logcat_<timestamp>.txt")
    args = parser.parse_args()

    # Clear existing logs
    clear_cmd = ["adb"]
    if args.serial:
        clear_cmd += ["-s", args.serial]
    clear_cmd += ["logcat", "-c"]
    subprocess.run(clear_cmd, capture_output=True)
    print(f"[logcat_filter] Cleared logcat buffer.", flush=True)

    # Resolve PID
    pid = get_pid(args.serial, args.package)
    if not pid:
        print(f"[logcat_filter] WARNING: Could not resolve PID for '{args.package}'.", file=sys.stderr)
        print(f"[logcat_filter] Is the app running? Streaming all logs instead.", file=sys.stderr)
        # Fall back to streaming all logs
        stream_cmd = ["adb"]
        if args.serial:
            stream_cmd += ["-s", args.serial]
        stream_cmd += ["logcat"]
        os.execvp("adb", stream_cmd)
        return

    print(f"[logcat_filter] Package: {args.package} | PID: {pid}", flush=True)
    print(f"[logcat_filter] Streaming logcat... (Ctrl+C to stop)\n", flush=True)
    stream_logcat(args.serial, pid, args.save)


if __name__ == "__main__":
    main()
