#!/usr/bin/env python3
"""
Simple log viewer for development.
Shows the last N lines from dev.log and can filter by patterns.
"""
import argparse
from pathlib import Path


def view_logs(lines=50, grep=None, follow=False):
    log_file = Path("logs/dev.log")

    if not log_file.exists():
        print(f"No log file found at {log_file}")
        print("Run 'just dev' first to start logging")
        return

    if follow:
        # For following, we'll use tail
        import subprocess

        cmd = ["tail", "-f", str(log_file)]
        if grep:
            # Add grep to filter
            cmd = ["tail", "-f", str(log_file), "|", "grep", "--line-buffered", grep]
            cmd = " ".join(cmd)
            subprocess.run(cmd, shell=True)
        else:
            subprocess.run(cmd)
    else:
        # Read last N lines
        with open(log_file) as f:
            all_lines = f.readlines()

        # Get last N lines
        last_lines = all_lines[-lines:] if lines < len(all_lines) else all_lines

        # Filter if grep pattern provided
        if grep:
            last_lines = [line for line in last_lines if grep.lower() in line.lower()]

        print("".join(last_lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="View development logs")
    parser.add_argument("-n", "--lines", type=int, default=50, help="Number of lines to show")
    parser.add_argument("-g", "--grep", help="Filter lines containing this pattern")
    parser.add_argument("-f", "--follow", action="store_true", help="Follow log file (like tail -f)")

    args = parser.parse_args()
    view_logs(args.lines, args.grep, args.follow)
