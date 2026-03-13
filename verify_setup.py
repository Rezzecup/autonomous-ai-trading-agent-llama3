#!/usr/bin/env python3
"""
Verify setup for Autonomous AI Trading Agent.
Run this after installation to ensure the environment is correct.
Run from the project directory: python verify_setup.py
"""

import sys
from pathlib import Path

# Change to script directory so config.yaml and imports are found
_script_dir = Path(__file__).resolve().parent
if Path.cwd() != _script_dir:
    import os
    os.chdir(_script_dir)
    sys.path.insert(0, str(_script_dir))


def check(name, ok, msg):
    status = "✓" if ok else "✗"
    print(f"  [{status}] {name}: {msg}")
    return ok


def main():
    print("Verifying Autonomous AI Trading Agent setup...\n")

    all_ok = True

    # Python version
    v = sys.version_info
    py_ok = v >= (3, 10)
    all_ok &= check("Python", py_ok, f"{v.major}.{v.minor}.{v.micro}" + (" (need 3.10+)" if not py_ok else ""))

    # Config
    try:
        cfg = Path("config.yaml")
        config_ok = cfg.exists()
        all_ok &= check("config.yaml", config_ok, "found" if config_ok else "missing — create from README")
    except Exception as e:
        all_ok &= check("config.yaml", False, str(e))

    # Dependencies
    deps = [
        ("ccxt", "Exchange connectivity"),
        ("requests", "HTTP (Chutes API)"),
        ("pandas", "Data processing"),
        ("ta", "Technical indicators"),
        ("yaml", "Config (PyYAML)"),
        ("dotenv", "Environment (python-dotenv)"),
    ]
    for mod, desc in deps:
        try:
            __import__(mod)
            all_ok &= check(desc, True, "OK")
        except ImportError as e:
            all_ok &= check(desc, False, f"Import error — run: pip install -r requirements.txt")

    # Project modules
    for mod in ["sentiment", "perceive", "reason", "act", "agent"]:
        try:
            __import__(mod)
            all_ok &= check(f"Module {mod}", True, "OK")
        except Exception as e:
            all_ok &= check(f"Module {mod}", False, str(e))

    print()
    if all_ok:
        print("All checks passed. Run: python agent.py --symbol BTC/USDT --exchange binance --mode paper")
    else:
        print("Some checks failed. Fix the issues above, then run verify_setup.py again.")
        sys.exit(1)


if __name__ == "__main__":
    main()
