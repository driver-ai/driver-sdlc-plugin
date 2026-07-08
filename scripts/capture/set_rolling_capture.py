"""Imperative shell: flip rolling_capture in $HOME/.driver/config.json (atomic, idempotent).

Usage: python3 set_rolling_capture.py --on | --off
Exit codes: 0 = flipped or already in target state; 1 = bad argv, unreadable/corrupt/non-dict
config (never clobbered), or write failure.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from capture_config_core import set_rolling_capture

USAGE = "usage: python3 set_rolling_capture.py --on | --off"


def main(argv: "list[str] | None" = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["--on"]:
        enabled = True
    elif args == ["--off"]:
        enabled = False
    else:
        print(USAGE, file=sys.stderr)
        return 1

    config_path = os.path.join(os.path.expanduser("~"), ".driver", "config.json")

    if not os.path.exists(config_path):
        if not enabled:
            print("Rolling capture is already stopped: no config file at "
                  f"{config_path} (none created).")
            return 0
        config = {}
    else:
        try:
            with open(config_path) as f:
                config = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"Refusing to modify {config_path}: could not read it as JSON "
                  f"({exc}). Fix or remove the file and re-run; it was left "
                  "untouched.", file=sys.stderr)
            return 1
        if not isinstance(config, dict):
            print(f"Refusing to modify {config_path}: expected a JSON object, "
                  f"found {type(config).__name__}. Fix the file and re-run; it "
                  "was left untouched.", file=sys.stderr)
            return 1

    new_config, changed = set_rolling_capture(config, enabled)
    if not changed:
        state = "started" if enabled else "stopped"
        print(f"Rolling capture is already {state}; {config_path} was left "
              "unchanged.")
        return 0

    # Atomic write: same-directory tmp + os.replace on the realpath-resolved
    # target, so a symlinked config is updated in place, never replaced by a
    # regular file.
    target = os.path.realpath(config_path)
    tmp = target + ".tmp." + str(os.getpid())
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(new_config, f, indent=2)
            f.write("\n")
        os.replace(tmp, target)
    except OSError as exc:
        print(f"Failed to write {config_path}: {exc}. The existing config was "
              "left untouched.", file=sys.stderr)
        return 1
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    if enabled:
        print(f"Rolling capture started: rolling_capture set to true in "
              f"{config_path}. New sessions will be recorded to the local "
              "rolling store (~/.driver/capture). All other settings were "
              "left unchanged.")
    else:
        print(f"Rolling capture stopped: rolling_capture set to false in "
              f"{config_path}. New sessions will not be recorded. "
              "Already-captured data is left untouched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
