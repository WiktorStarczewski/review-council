"""Prove each sealed isolation regression and the unaffected cache behavior."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def load(snapshot):
    name = "cache_isolation_" + snapshot
    spec = importlib.util.spec_from_file_location(name, ROOT / snapshot / "cache.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def tenant_probe(module):
    cache = module.TenantCache(clock=lambda: 0)
    cache.put("first", "profile", {"owner": "first"}, 10)
    other_before_write = cache.get("second", "profile")
    cache.put("second", "profile", {"owner": "second"}, 10)
    return {"other_before_write": other_before_write, "first_after_write": cache.get("first", "profile")}


def alias_probe(module):
    cache = module.TenantCache(clock=lambda: 0)
    cache.put("tenant", "profile", {"settings": {"theme": "light"}}, 10)
    value = cache.get("tenant", "profile")
    value["settings"]["theme"] = "dark"
    return cache.get("tenant", "profile")["settings"]["theme"]


def write_copy_control(module):
    cache = module.TenantCache(clock=lambda: 0)
    original = {"settings": {"theme": "light"}}
    cache.put("tenant", "profile", original, 10)
    original["settings"]["theme"] = "dark"
    return cache.get("tenant", "profile")["settings"]["theme"]


def expiry_control(module):
    now = [10]
    cache = module.TenantCache(clock=lambda: now[0])
    cache.put("tenant", "profile", {"state": "present"}, 10)
    initial = cache.get("tenant", "profile")
    now[0] = 20
    return initial, cache.get("tenant", "profile"), len(cache)


def lru_control(module):
    cache = module.TenantCache(max_entries=2, clock=lambda: 0)
    cache.put("tenant", "a", {"value": 1}, 10)
    cache.put("tenant", "b", {"value": 2}, 10)
    cache.get("tenant", "a")
    cache.put("tenant", "c", {"value": 3}, 10)
    return cache.get("tenant", "a"), cache.get("tenant", "b"), cache.get("tenant", "c")


def invalidate_control(module):
    cache = module.TenantCache(clock=lambda: 0)
    cache.put("tenant", "a", {"value": 1}, 10)
    return cache.invalidate("tenant", "a"), cache.invalidate("tenant", "a"), cache.get("tenant", "a")


def run_checks():
    before, after = load("before"), load("after")
    checks = []

    def check(identifier, kind, actual, expected):
        checks.append({"id": identifier, "kind": kind, "passed": actual == expected,
                       "detail": f"expected {expected!r}; observed {actual!r}"})

    check("tenant-key-before", "baseline", tenant_probe(before),
          {"other_before_write": None, "first_after_write": {"owner": "first"}})
    check("tenant-key", "defect", tenant_probe(after),
          {"other_before_write": {"owner": "first"}, "first_after_write": {"owner": "second"}})
    check("nested-read-alias-before", "baseline", alias_probe(before), "light")
    check("nested-read-alias", "defect", alias_probe(after), "dark")
    check("write-owns-nested-copy", "clean-control", write_copy_control(after), "light")
    check("exact-expiry", "clean-control", expiry_control(after), ({"state": "present"}, None, 0))
    check("lru-eviction", "clean-control", lru_control(after), ({"value": 1}, None, {"value": 3}))
    check("single-tenant-invalidation", "clean-control", invalidate_control(after), (True, False, None))
    return {"case": "cache-isolation", "checks": checks, "passed": all(row["passed"] for row in checks)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the sealed runtime checks as JSON")
    args = parser.parse_args()
    result = run_checks()
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for check in result["checks"]:
            print(f"{'PASS' if check['passed'] else 'FAIL'} {check['kind']} {check['id']}: {check['detail']}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
