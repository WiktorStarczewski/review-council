"""Prove each sealed regression and the unaffected ledger behavior."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def load(snapshot):
    name = "boundary_ledger_" + snapshot
    spec = importlib.util.spec_from_file_location(name, ROOT / snapshot / "ledger.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def quota_probe(module):
    ledger = module.DailyLedger(10)
    ledger.record(module.Entry("first", "account", 6, 1))
    try:
        ledger.record(module.Entry("second", "account", 4, 2))
    except ValueError:
        accepted = False
    else:
        accepted = True
    return {"accepted": accepted, "total": ledger.daily_total("account", 2)}


def window_probe(module):
    ledger = module.DailyLedger(50)
    ledger.record(module.Entry("inside", "account", 1, 9))
    ledger.record(module.Entry("endpoint", "account", 1, 10))
    return [entry.event_id for entry in ledger.entries_between("account", 0, 10)]


def replay_control(module):
    ledger = module.DailyLedger(10)
    entry = module.Entry("event", "account", 4, 1)
    ledger.record(entry)
    ledger.record(entry)
    return ledger.daily_total("account", 1), ledger.remaining("account", 1)


def rejection_control(module):
    ledger = module.DailyLedger(10)
    ledger.record(module.Entry("first", "account", 6, 1))
    try:
        ledger.record(module.Entry("over", "account", 5, 2))
    except ValueError:
        rejected = True
    else:
        rejected = False
    return rejected, ledger.daily_total("account", 2), ledger.event("account", "over")


def day_account_control(module):
    ledger = module.DailyLedger(10)
    for entry in (module.Entry("a", "first", 8, 0), module.Entry("b", "first", 8, 86400),
                  module.Entry("a", "second", 8, 0)):
        ledger.record(entry)
    return [ledger.daily_total(account, timestamp)
            for account, timestamp in (("first", 0), ("first", 86400), ("second", 0))]


def interior_window_control(module):
    ledger = module.DailyLedger(10)
    for entry in (module.Entry("inside", "first", 1, 2), module.Entry("outside", "first", 1, 8),
                  module.Entry("other", "second", 1, 2)):
        ledger.record(entry)
    return [entry.event_id for entry in ledger.entries_between("first", 0, 5)]


def run_checks():
    before, after = load("before"), load("after")
    checks = []

    def check(identifier, kind, actual, expected):
        checks.append({"id": identifier, "kind": kind, "passed": actual == expected,
                       "detail": f"expected {expected!r}; observed {actual!r}"})

    check("quota-equality-before", "baseline", quota_probe(before), {"accepted": True, "total": 10})
    check("quota-equality", "defect", quota_probe(after), {"accepted": False, "total": 6})
    check("exclusive-window-end-before", "baseline", window_probe(before), ["inside"])
    check("exclusive-window-end", "defect", window_probe(after), ["inside", "endpoint"])
    check("idempotent-replay", "clean-control", replay_control(after), (4, 6))
    check("over-quota-is-atomic", "clean-control", rejection_control(after), (True, 6, None))
    check("accounts-and-days", "clean-control", day_account_control(after), [8, 8, 8])
    check("interior-window-filter", "clean-control", interior_window_control(after), ["inside"])
    return {"case": "boundary-ledger", "checks": checks, "passed": all(row["passed"] for row in checks)}


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
