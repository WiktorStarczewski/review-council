#!/usr/bin/env python3
"""Validate a findings JSON file against ../../schema/findings.schema.json (stdlib only).

Usage: validate-findings.py <file.json>
  exit 0: prints the number of findings
  exit 2: prints `invalid: <reason>` to stderr
"""
import json
import math
import os
import sys

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'schema', 'findings.schema.json')


def fail(msg):
    print(f"invalid: {msg}", file=sys.stderr)
    sys.exit(2)


def _non_finite(token):
    fail(f"non-finite number: {token}")


def check(obj, sch, path):
    t = sch.get('type')
    if t == 'object':
        if not isinstance(obj, dict):
            fail(f"{path}: expected object")
        for k in sch.get('required', []):
            if k not in obj:
                fail(f"{path}: missing '{k}'")
        props = sch.get('properties', {})
        if sch.get('additionalProperties') is False:
            for k in obj:
                if k not in props:
                    fail(f"{path}: unexpected key '{k}'")
        for k, v in obj.items():
            if k in props:
                check(v, props[k], f"{path}.{k}")
    elif t == 'array':
        if not isinstance(obj, list):
            fail(f"{path}: expected array")
        for i, v in enumerate(obj):
            check(v, sch['items'], f"{path}[{i}]")
    elif t == 'string':
        if not isinstance(obj, str):
            fail(f"{path}: expected string")
        if len(obj) < sch.get('minLength', 0):
            fail(f"{path}: empty string")
        if 'enum' in sch and obj not in sch['enum']:
            fail(f"{path}: '{obj}' not in {sch['enum']}")
    elif t == 'integer':
        if not isinstance(obj, int) or isinstance(obj, bool):
            fail(f"{path}: expected integer")
        if obj < sch.get('minimum', -10**18):
            fail(f"{path}: below minimum {sch.get('minimum')}")
    elif t == 'number':
        if not isinstance(obj, (int, float)) or isinstance(obj, bool):
            fail(f"{path}: expected number")
        if not math.isfinite(obj):
            fail(f"{path}: non-finite number")
        if obj < sch.get('minimum', -1e18) or obj > sch.get('maximum', 1e18):
            fail(f"{path}: out of range")


def main():
    if len(sys.argv) != 2:
        fail("usage: validate-findings.py <file.json>")
    try:
        with open(sys.argv[1]) as f:
            # json.load accepts the JavaScript-only literals NaN/Infinity/-Infinity, and every range
            # comparison against NaN is False — so `"confidence": NaN` would sail through untouched.
            doc = json.load(f, parse_constant=_non_finite)
    except Exception as e:  # noqa: BLE001 — any read/parse failure is 'invalid'
        fail(f"cannot read JSON: {e}")
    with open(SCHEMA) as f:
        schema = json.load(f)
    check(doc, schema, '$')
    print(len(doc['findings']))


if __name__ == '__main__':
    main()
