"""Explicit simulator checks with failure aggregation and deterministic cleanup."""

from __future__ import annotations

import os
from contextlib import contextmanager


def run_criteria(title, criteria):
    """Run every check, report each failure, and return a failing process status."""
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70 + "\n")
    if not criteria:
        print("ERROR: no acceptance criteria configured")
        return 2
    results = []
    for identifier, description, check in criteria:
        print(f"[{identifier}] {description}")
        try:
            message = check()
        except Exception as error:
            results.append((identifier, False, f"✗ Failed: {str(error) or type(error).__name__}"))
        else:
            results.append((identifier, True, message))
    print("\n" + "=" * 70 + "\nRESULTS\n" + "=" * 70)
    for identifier, _success, message in results:
        print(f"[{identifier}] {message}")
    passed = sum(1 for _identifier, success, _message in results if success)
    failed = len(results) - passed
    print(f"SUMMARY: {passed}/{len(results)} passed, {failed}/{len(results)} failed")
    return 1 if failed else 0


@contextmanager
def simulation_world(**kwargs):
    """Use only a dummy display and always close the world, including failed checks."""
    from sim.world import World

    previous = os.environ.get("SDL_VIDEODRIVER")
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    try:
        world = World(**kwargs)
        try:
            yield world
        finally:
            world.quit()
    finally:
        if previous is None:
            os.environ.pop("SDL_VIDEODRIVER", None)
        else:
            os.environ["SDL_VIDEODRIVER"] = previous
