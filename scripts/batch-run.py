#!/usr/bin/env python3
"""
Parallel job runner — replacement for bash `&` + `wait -n` on macOS.
Reads a job file (one shell command per line), runs up to N concurrently.

Usage:
  batch-run.py --jobs FILE --parallel N
"""

import sys
import os
import subprocess
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed


def run_cmd(cmd: str) -> tuple[int, list[str]]:
    """Run one shell command, return (exit_code, stderr_tail)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=300
        )
        return (result.returncode, result.stderr.split("\n")[-3:])
    except subprocess.TimeoutExpired:
        return (99, ["timeout"])
    except Exception as e:
        return (99, [str(e)])


def main():
    parser = argparse.ArgumentParser(description="Parallel job runner")
    parser.add_argument("--jobs", required=True, help="Job file (one cmd per line)")
    parser.add_argument("--parallel", type=int, default=5, help="Max concurrent jobs")
    args = parser.parse_args()

    if not os.path.isfile(args.jobs):
        print(f"Job file not found: {args.jobs}", file=sys.stderr)
        sys.exit(1)

    with open(args.jobs) as f:
        commands = [line.strip() for line in f if line.strip()]

    if not commands:
        print("No jobs to run.", file=sys.stderr)
        sys.exit(0)

    total = len(commands)
    completed = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(run_cmd, cmd): i for i, cmd in enumerate(commands)}

        for fut in as_completed(futures):
            idx = futures[fut]
            code, err_tail = fut.result()
            completed += 1
            if code != 0:
                failed += 1
            print(f"\r   🔍 {completed}/{total} completed ({failed} failed)",
                  end="", flush=True, file=sys.stderr)

    print("", file=sys.stderr)  # newline

    if failed > 0 and failed == total:
        print(f"All {total} jobs failed.", file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
