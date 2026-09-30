"""Check a host quality API against frozen cases without requiring source-byte identity."""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / 'reference/bench_quality.py'
sys.dont_write_bytecode = True
_sequence = 0


def load_quality(path):
    """Give each scorer its own relative-import namespace and correctness module."""
    global _sequence
    _sequence += 1
    path = Path(path)
    name = 'build_quality_compatibility_' + str(_sequence)
    for previous in tuple(sys.modules):
        if previous == name or previous.startswith(name + '.'):
            del sys.modules[previous]
    package = ModuleType(name)
    package.__path__ = [str(path.parent)]
    sys.modules[name] = package
    spec = importlib.util.spec_from_file_location(name + '.bench_quality', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def scoring_ast(path):
    tree = ast.parse(Path(path).read_text())
    functions = {node.name: ast.dump(node, include_attributes=False)
                 for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in ('score_run', 'compare_quality')}
    encoded = json.dumps(functions, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def check_compatibility(path):
    scorer = load_quality(path)
    cases = []
    for identifier in ('incremental-build-a', 'incremental-build-b'):
        case = json.loads((ROOT / identifier / 'case.json').read_text())
        try:
            accepted = scorer._rubric(case['behavior_rubric']) == case['behavior_rubric']
            score = scorer.score_run(case, {'summary': 'Compatibility only', 'findings': []}, None, None, None)
            incomplete = scorer.compare_quality({'valid': False, 'run_quality': score},
                                                {'valid': False, 'run_quality': score})
            passed = (accepted and score['score_version'] == 'quality-v1' and not score['confirmed']
                      and score['quality_score'] is None and incomplete['acceptable'] is False
                      and isinstance(incomplete['reasons'], list) and bool(incomplete['reasons']))
            detail = 'rubric and API accepted; incomplete judgments remain unscored and non-retainable'
        except Exception as error:
            passed = False
            detail = type(error).__name__ + ': ' + str(error)
        cases.append({'case': identifier, 'passed': passed, 'detail': detail})
    return {'passed': all(row['passed'] for row in cases), 'cases': cases,
            'observed_scorer_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'scoring_ast_matches_reference': scoring_ast(path) == scoring_ast(REFERENCE),
            'identity_policy': 'historical references are frozen; current source hash is an observation only'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scorer', type=Path, default=REFERENCE)
    args = parser.parse_args()
    result = check_compatibility(args.scorer)
    print(json.dumps(result, sort_keys=True))
    sys.exit(0 if result['passed'] else 1)
