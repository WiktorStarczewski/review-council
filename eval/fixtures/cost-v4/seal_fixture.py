"""Freeze or verify fixture-local artifacts and their dated historical provenance."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
RECEIPT = ROOT / 'freeze.json'


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifacts():
    return {str(path.relative_to(ROOT)): checksum(path) for path in sorted(ROOT.rglob('*'))
            if path.is_file() and path != RECEIPT and '__pycache__' not in path.parts}


def write_seal():
    provenance = json.loads((ROOT / 'provenance.json').read_text())
    reference = json.loads((ROOT / 'reference/original-freeze.json').read_text())
    for relative, expected in provenance['retained_artifacts'].items():
        if checksum(ROOT / relative) != expected:
            raise ValueError('retained source no longer matches the approved original: ' + relative)
    if checksum(ROOT / 'reference/bench_quality.py') != reference['scorer_sha256']:
        raise ValueError('frozen quality reference changed')
    if checksum(ROOT / 'reference/bench_score.py') != reference['correctness_scorer_sha256']:
        raise ValueError('frozen correctness reference changed')
    cases = {}
    for identifier in ('incremental-build-a', 'incremental-build-b'):
        case = json.loads((ROOT / identifier / 'case.json').read_text())
        canonical = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        cases[identifier] = {'case_sha256': canonical(case), 'rubric_sha256': canonical(case['behavior_rubric'])}
    value = {'schema_version': 1, 'captured_on': reference['frozen_on'], 'score_version': 'quality-v1',
             'scorer_sha256': reference['scorer_sha256'],
             'correctness_scorer_sha256': reference['correctness_scorer_sha256'],
             'scorer_identity_scope': 'immutable dated reference files, never the current host scorer',
             'original_seal_sha256': provenance['original_seal_sha256'],
             'cases': cases, 'artifacts': artifacts()}
    RECEIPT.write_text(json.dumps(value, indent=2) + '\n')


def verify():
    receipt = json.loads(RECEIPT.read_text())
    current = artifacts()
    mismatches = sorted(path for path in set(current) | set(receipt['artifacts'])
                        if current.get(path) != receipt['artifacts'].get(path))
    return {'passed': not mismatches, 'mismatches': mismatches,
            'artifact_count': len(current), 'seal_sha256': checksum(RECEIPT)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    if args.write:
        write_seal()
    result = verify()
    print(json.dumps(result, sort_keys=True))
    sys.exit(0 if result['passed'] else 1)
