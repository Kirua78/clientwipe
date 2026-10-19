#!/usr/bin/env python3
"""Standalone entry point: seeds a ClientWipe demo/test sandbox.

Thin wrapper around clientwipe.demo_sandbox.create_sandbox so the exact
same logic is used both for the local one-command demo and for
real-condition testing on a disposable VM (see README.md > "Test en
conditions reelles"). Requires ClientWipe to be installed (`pip install
-e .` from the repo root, or via install.sh on the test VM).
"""
from __future__ import annotations

import sys
from pathlib import Path

from clientwipe.demo_sandbox import create_sandbox

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "demo/sandbox"
    created = create_sandbox(Path(target))
    print(f"Sandbox created at {created}")
