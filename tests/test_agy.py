"""Antigravity (agy) host, bundle, installer, escalation chain, and stream-audit tests."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / 'plugins/review-council/scripts'
LIB = SCRIPTS / 'lib'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AgyHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='agy-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.clean_env = {
            k: v for k, v in os.environ.items()
            if not k.startswith(('REV_', 'REVIEW_COUNCIL_'))
        }
        self.clean_env.update(
            HOME=str(self.root),
            REVIEW_COUNCIL_HOST='agy',
            REVIEW_COUNCIL_CONFIG=str(self.root / 'absent-config.json'),
        )

    def load_roster(self, host='agy'):
        env = dict(self.clean_env, REVIEW_COUNCIL_HOST=host)
        with patch.dict(os.environ, env, clear=True):
            return load('roster_' + host, LIB / 'roster.py')

    def load_workhorse(self, host='agy'):
        env = dict(self.clean_env, REVIEW_COUNCIL_HOST=host)
        with patch.dict(os.environ, env, clear=True):
            return load('workhorse_' + host, LIB / 'workhorse.py')

    def test_bundle_build_structure_and_strict_validation(self):
        builder = load('build_agy_plugin', REPO / 'scripts/build-agy-plugin.py')
        dest = self.root / 'out/review-council'
        self.assertEqual(builder.build(dest), dest)
        manifest = json.loads((dest / 'plugin.json').read_text(encoding='utf-8'))
        source_manifest = json.loads(
            (REPO / 'plugins/review-council/.claude-plugin/plugin.json').read_text(encoding='utf-8')
        )
        self.assertEqual(manifest['name'], 'review-council')
        self.assertEqual(manifest['version'], source_manifest['version'])
        self.assertTrue((dest / 'skills/rev/SKILL.md').is_file())
        self.assertTrue((dest / 'skills/rev/phases/10-setup.md').is_file())
        self.assertTrue((dest / 'skills/stack/SKILL.md').is_file())
        self.assertTrue((dest / 'docs/agy.md').is_file())
        self.assertTrue((dest / 'scripts/seats.d/agy.sh').is_file())
        self.assertIn('REVIEW_COUNCIL_HOST=agy', (dest / 'skills/rev/SKILL.md').read_text())
        self.assertIn('Exit 4 means the Antigravity (`agy`) writer is missing',
                      (dest / 'skills/rev/SKILL.md').read_text())
        self.assertIn('Adapters `agy`, `codex` and `claude` launch through `rev-seat.sh`.',
                      (dest / 'skills/rev/SKILL.md').read_text())
        self.assertIn('REVIEW_COUNCIL_HOST=agy', (dest / 'skills/stack/SKILL.md').read_text())
        self.assertIn('hydrogen', (dest / 'skills/rev/SKILL.md').read_text())
        self.assertIn('REVIEW_COUNCIL_HOST=agy', (dest / 'scripts/roster.sh').read_text())
        self.assertIn('REVIEW_COUNCIL_HOST=agy', (dest / 'scripts/stack.sh').read_text())
        for absent in ('.claude-plugin', '.codex-plugin', '.cursor-plugin', 'hooks',
                       'codex-skills', 'cursor-skills', 'pi-skills'):
            self.assertFalse((dest / absent).exists(), absent)
        # Replacing an existing owned bundle cleanly drops stale files.
        stale = dest / 'stale.txt'
        stale.write_text('old\n', encoding='utf-8')
        self.assertEqual(builder.build(dest), dest)
        self.assertFalse(stale.exists())
        # Refusing an existing directory whose plugin.json is valid non-object JSON raises ValueError.
        non_obj_dest = self.root / 'non-obj/review-council'
        non_obj_dest.mkdir(parents=True)
        (non_obj_dest / 'plugin.json').write_text('[]\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            builder.build(non_obj_dest)
        if shutil.which('agy'):
            proc = subprocess.run(
                ['agy', 'plugin', 'validate', '--strict', str(dest)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_install_agy_script_options_source_and_ref_clone(self):
        installer = REPO / 'install-agy.sh'
        help_res = subprocess.run(['bash', str(installer), '--help'],
                                  capture_output=True, text=True, check=False)
        self.assertEqual(help_res.returncode, 0)
        self.assertIn('install-agy.sh [--ref <branch-or-tag>]', help_res.stdout)

        bad_opt = subprocess.run(['bash', str(installer), '--nope'],
                                 capture_output=True, text=True, check=False)
        self.assertEqual(bad_opt.returncode, 2)

        rel_env = dict(os.environ, REVIEW_COUNCIL_SOURCE=str(REPO),
                       REVIEW_COUNCIL_AGY_DEST='relative/review-council')
        rel_res = subprocess.run(['bash', str(installer)], env=rel_env,
                                 capture_output=True, text=True, check=False)
        self.assertEqual(rel_res.returncode, 2)

        bad_name = subprocess.run(
            ['bash', str(installer)],
            env=dict(os.environ, REVIEW_COUNCIL_SOURCE=str(REPO),
                     REVIEW_COUNCIL_AGY_DEST=str(self.root / 'wrong-name')),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(bad_name.returncode, 2)

        dest = self.root / 'gemini-plugins/review-council'
        ok = subprocess.run(
            ['bash', str(installer)],
            env=dict(os.environ, REVIEW_COUNCIL_SOURCE=str(REPO),
                     REVIEW_COUNCIL_AGY_DEST=str(dest)),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertTrue((dest / 'plugin.json').is_file())
        self.assertIn(str(dest), ok.stdout)

        # Clone path passes selected --ref to git.
        bindir = self.root / 'bin'
        bindir.mkdir()
        capture = self.root / 'git-args.txt'
        fake_git = bindir / 'git'
        fake_git.write_text('#!/bin/bash\nprintf "%s\\n" "$*" > "$CAPTURE"\nexit 9\n')
        fake_git.chmod(0o755)
        env = dict(os.environ)
        env.pop('REVIEW_COUNCIL_SOURCE', None)
        env.update(
            PATH=str(bindir) + os.pathsep + env.get('PATH', ''),
            REVIEW_COUNCIL_AGY_DEST=str(self.root / 'cloned/review-council'),
            CAPTURE=str(capture),
        )
        clone_res = subprocess.run(['bash', str(installer), '--ref', 'review-council--v0.9.16'],
                                   env=env, capture_output=True, text=True, check=False)
        self.assertEqual(clone_res.returncode, 9)
        self.assertIn('review-council--v0.9.16', capture.read_text(encoding='utf-8'))

    def test_panel_request_agy_chain_and_toc_refusal(self):
        pr = load('panel_request_under_test', LIB / 'panel_request.py')
        self.assertEqual(
            pr.chain_for('agy'),
            ('hydrogen', 'luna', 'sonnet', 'sol', 'neon', 'opus'),
        )
        session = self.root / 'sess'
        base = self.root / 'config.json'
        base.write_text('{}\n', encoding='utf-8')
        cfg_path = pr.write_session(session, 'review branch', base, host='agy')
        cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        req = json.loads((session / 'panel-request.json').read_text(encoding='utf-8'))
        self.assertEqual(cfg['agy_models'], ['latest-hydrogen'] * 4)
        self.assertEqual(cfg['panel_fallback'], 'luna')
        self.assertEqual(req['chain'], ['hydrogen', 'luna', 'sonnet', 'sol', 'neon', 'opus'])

        explicit_neon = pr.write_session(session / 'neon', '2*neon', base, host='agy')
        self.assertEqual(
            json.loads(explicit_neon.read_text(encoding='utf-8'))['agy_models'],
            ['latest-neon', 'latest-neon'],
        )

        # Google ToC compliance: hydrogen/neon and agy_models are forbidden off agy host.
        for host in ('claude', 'codex', 'cursor', 'pi'):
            with self.assertRaises(ValueError, msg=host):
                pr.session_config({}, pr.parse_panel_request('4*hydrogen'), host=host)
            with self.assertRaises(ValueError, msg=host):
                pr.session_config({}, pr.parse_panel_request('2*neon'), host=host)
            with self.assertRaises(ValueError, msg=host):
                pr.session_config({'agy_models': ['latest-hydrogen']},
                                 pr.parse_panel_request('4*luna'), host=host)

    def test_roster_agy_detection_fallback_and_off_host_isolation(self):
        bindir = self.root / 'agy-bin'
        bindir.mkdir()
        agy_shim = bindir / 'agy'
        agy_shim.write_text(
            '#!/bin/bash\n'
            'if [ "${1:-}" = models ]; then\n'
            '  printf "gemini-4-hydrogen-low    Gemini 4 Hydrogen (Low)\\n"\n'
            '  printf "gemini-4-hydrogen-high   Gemini 4 Hydrogen (High)\\n"\n'
            '  printf "gemini-4-hydrogen-xhigh  Gemini 4 Hydrogen (Extra High)\\n"\n'
            '  printf "gemini-4-neon-xhigh      Gemini 4 Neon (Extra High)\\n"\n'
            '  exit 0\n'
            'fi\n'
            'if [ "${1:-}" = "--version" ]; then\n'
            '  echo "1.5.15"\n'
            '  exit 0\n'
            'fi\n'
            'echo "{\\"event\\":\\"result\\",\\"result\\":{\\"status\\":\\"SUCCESS\\",\\"response\\":\\"OK\\"}}"\n',
            encoding='utf-8',
        )
        agy_shim.chmod(0o755)
        cfg_file = self.root / 'agy-cfg.json'
        cfg_file.write_text(
            json.dumps({'agy_models': ['latest-hydrogen', 'latest-neon'],
                        'min_labs': 1, 'claude_seats': 0, 'extras': False}),
            encoding='utf-8',
        )
        env = dict(
            self.clean_env,
            PATH=str(bindir) + ':/usr/bin:/bin',
            REVIEW_COUNCIL_HOST='agy',
            REVIEW_COUNCIL_CONFIG=str(cfg_file),
        )
        out = subprocess.run([str(SCRIPTS / 'roster.sh'), '--json'],
                             env=env, capture_output=True, text=True, check=False)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        doc = json.loads(out.stdout)
        self.assertEqual(
            [(s['adapter'], s['lab'], s['model'], s['effort'], bool(s.get('padded')))
             for s in doc['seats']],
            [
                ('agy', 'google', 'gemini-4-hydrogen-xhigh', 'xhigh', False),
                ('agy', 'google', 'gemini-4-neon-xhigh', 'xhigh', False),
                ('agy', 'google', 'gemini-4-hydrogen-xhigh', 'xhigh', True),
            ],
        )

        # Normal mode fallback to luna when agy binary is absent.
        fallback_cfg = self.root / 'agy-fallback.json'
        fallback_cfg.write_text(json.dumps({
            'panel_mode': 'normal', 'panel_family': 'hydrogen', 'panel_fallback': 'luna',
            'agy_models': ['latest-hydrogen'] * 2, 'claude_seats': 0,
            'extras': False, 'min_labs': 1,
        }), encoding='utf-8')
        codex_cache = self.root / 'models_cache.json'
        codex_cache.write_text(json.dumps({'models': [
            {'slug': 'gpt-5.6-luna', 'visibility': 'list',
             'supported_reasoning_levels': [{'effort': 'xhigh'}, {'effort': 'high'}]}
        ]}), encoding='utf-8')
        codex_bin = self.root / 'codex-only'
        codex_bin.mkdir()
        fake_codex = codex_bin / 'codex'
        fake_codex.write_text('#!/bin/bash\n[ "${1:-}" = login ] && echo "Logged in" && exit 0\necho "0.1.0"\n')
        fake_codex.chmod(0o755)
        fb_env = dict(
            self.clean_env,
            PATH=str(codex_bin) + ':/usr/bin:/bin',
            REVIEW_COUNCIL_HOST='agy',
            REVIEW_COUNCIL_CONFIG=str(fallback_cfg),
            REVIEW_COUNCIL_CODEX_MODELS_CACHE=str(codex_cache),
        )
        fb_out = subprocess.run([str(SCRIPTS / 'roster.sh'), '--json'],
                                env=fb_env, capture_output=True, text=True, check=False)
        self.assertEqual(fb_out.returncode, 0, fb_out.stdout + fb_out.stderr)
        fb_doc = json.loads(fb_out.stdout)
        self.assertTrue(all(s['adapter'] == 'codex' and s['model'] == 'gpt-5.6-luna'
                            for s in fb_doc['seats']))

        # Off-agy host rejects agy_models with exit 6 and never probes agy.
        off_out = subprocess.run(
            [str(SCRIPTS / 'roster.sh'), '--json'],
            env=dict(env, REVIEW_COUNCIL_HOST='claude'),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(off_out.returncode, 6)
        self.assertEqual(json.loads(off_out.stdout).get('strict_class'), 'config')

        # Excluding agy with agy_models returns clean exit 6 config refusal (no crash).
        excl_cfg = self.root / 'agy-exclude.json'
        excl_cfg.write_text(
            json.dumps({'agy_models': ['latest-hydrogen'], 'exclude': ['agy'],
                        'min_labs': 1, 'claude_seats': 0, 'extras': False}),
            encoding='utf-8',
        )
        excl_out = subprocess.run(
            [str(SCRIPTS / 'roster.sh'), '--json'],
            env=dict(env, REVIEW_COUNCIL_CONFIG=str(excl_cfg)),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(excl_out.returncode, 6, excl_out.stdout + excl_out.stderr)
        self.assertEqual(json.loads(excl_out.stdout).get('strict_class'), 'config')

        # Documented low/medium agy_effort works both with and without agy_models.
        for cfg_payload in (
            {'agy_models': ['latest-hydrogen'], 'agy_effort': 'low',
             'min_labs': 1, 'claude_seats': 0, 'extras': False},
            {'agy_effort': 'low', 'min_labs': 1, 'claude_seats': 0, 'extras': False},
        ):
            eff_cfg = self.root / 'agy-effort-low.json'
            eff_cfg.write_text(json.dumps(cfg_payload), encoding='utf-8')
            eff_out = subprocess.run(
                [str(SCRIPTS / 'roster.sh'), '--json'],
                env=dict(env, REVIEW_COUNCIL_CONFIG=str(eff_cfg)),
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(eff_out.returncode, 0, eff_out.stdout + eff_out.stderr)
            agy_rows = [s for s in json.loads(eff_out.stdout)['seats'] if s['adapter'] == 'agy']
            self.assertTrue(agy_rows)
            self.assertTrue(all(s['model'] == 'gemini-4-hydrogen-low' and s['effort'] == 'low'
                                for s in agy_rows))

        # Invalid agy_effort without agy_models and off-host agy_effort both exit 6.
        bad_eff = self.root / 'agy-effort-bad.json'
        bad_eff.write_text(json.dumps({'agy_effort': 'bogus'}), encoding='utf-8')
        bad_out = subprocess.run(
            [str(SCRIPTS / 'roster.sh'), '--json'],
            env=dict(env, REVIEW_COUNCIL_CONFIG=str(bad_eff)),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(bad_out.returncode, 6)
        self.assertEqual(json.loads(bad_out.stdout).get('strict_class'), 'config')

        low_only = self.root / 'agy-effort-low-only.json'
        low_only.write_text(json.dumps({'agy_effort': 'low'}), encoding='utf-8')
        off_eff = subprocess.run(
            [str(SCRIPTS / 'roster.sh'), '--json'],
            env=dict(env, REVIEW_COUNCIL_HOST='claude', REVIEW_COUNCIL_CONFIG=str(low_only)),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(off_eff.returncode, 6)

        # brief_line does not print agy x unavailable when panel_mode omits agy (4*luna / high).
        roster_mod = self.load_roster('agy')
        banner = roster_mod.brief_line(
            {'seats': [{'seat': 'codex-luna', 'lab': 'openai', 'adapter': 'codex',
                        'model': 'gpt-5.6-luna', 'effort': 'xhigh', 'extra': False}],
             'excluded': [], 'degraded': False},
            {'codex-luna': 'codex'},
        )
        self.assertNotIn('agy', banner)

    def test_workhorse_agy_chain_launch_and_toc_guard(self):
        wh_agy = self.load_workhorse('agy')
        self.assertEqual(
            wh_agy.order_for('agy'),
            ('hydrogen', 'luna', 'sonnet', 'sol', 'neon', 'opus'),
        )
        rec = wh_agy.resolve_available(
            'agy',
            hydrogen=('gemini-4-hydrogen-high', 'high'),
            luna=('gpt-5.6-luna', 'high'),
            sonnet={'adapter': 'claude', 'model': 'sonnet', 'effort': 'high'},
            sol=('gpt-5.6-sol', 'high'),
            neon=('gemini-4-neon-high', 'high'),
            opus={'adapter': 'claude', 'model': 'opus', 'effort': 'high'},
        )
        self.assertEqual(rec['family'], 'hydrogen')
        self.assertEqual(
            rec['available'],
            ['hydrogen', 'luna', 'sonnet', 'sol', 'neon', 'opus'],
        )
        plan_spec = wh_agy.launch_spec(rec, 'plan', self.root, self.root,
                                       self.root / 'prompt.md')
        self.assertIn('--sandbox', plan_spec['argv'])
        self.assertTrue(any(arg.startswith('--print=Read ') for arg in plan_spec['argv']))
        impl_spec = wh_agy.launch_spec(rec, 'implement', self.root, self.root,
                                       self.root / 'prompt.md', cluster='C-01')
        self.assertIn('--dangerously-skip-permissions', impl_spec['argv'])
        with self.assertRaises(ValueError):
            wh_agy.launch_spec(rec, 'review', self.root, self.root,
                               self.root / 'prompt.md', out=self.root / 'out.json')

        # Off-agy host must refuse hydrogen/neon workhorses and never run agy in _run_exec.
        for host in ('claude', 'codex', 'cursor', 'pi'):
            with self.assertRaises(ValueError, msg=host):
                wh_agy.resolve_available(host, hydrogen=('gemini-4-hydrogen-high', 'high'))
            with self.assertRaises(ValueError, msg=host):
                wh_agy.resolve_available(host, neon=('gemini-4-neon-high', 'high'))

        # Verify escalation sequence across sol -> neon -> opus on agy session.
        session = self.root / 'esc-session'
        session.mkdir()
        wh_agy.write_record(session / 'workhorse.json', rec)
        rows = [{'seat': 'codex-sol', 'adapter': 'codex', 'model': 'gpt-5.6-sol',
                 'effort': 'high', 'extra': False}]
        (session / 'roster.json').write_text(json.dumps({'seats': rows}), encoding='utf-8')
        cands = {
            'hydrogen': {'adapter': 'agy', 'model': 'gemini-4-hydrogen-high', 'effort': 'high', 'lab': 'google'},
            'luna': {'adapter': 'codex', 'model': 'gpt-5.6-luna', 'effort': 'high', 'lab': 'openai'},
            'sonnet': {'adapter': 'claude', 'model': 'sonnet', 'effort': 'high', 'lab': 'anthropic'},
            'sol': {'adapter': 'codex', 'model': 'gpt-5.6-sol', 'effort': 'high', 'lab': 'openai'},
            'neon': {'adapter': 'agy', 'model': 'gemini-4-neon-high', 'effort': 'high', 'lab': 'google'},
            'opus': {'adapter': 'claude', 'model': 'opus', 'effort': 'high', 'lab': 'anthropic'},
        }
        chosen, existing = wh_agy.choose_escalation('agy', 'sol', rows, cands)
        self.assertFalse(existing)
        self.assertEqual((chosen['family'], chosen['adapter'], chosen['model']),
                         ('neon', 'agy', 'gemini-4-neon-high'))

        # Google ToC: _run_exec refuses running an agy spec without REVIEW_COUNCIL_HOST=agy.
        with patch.dict(os.environ, {'REVIEW_COUNCIL_HOST': 'claude'}, clear=False):
            plan_spec_out = dict(plan_spec, out=str(self.root / 'refused-plan.md'))
            self.assertEqual(wh_agy._run_exec(plan_spec_out), 1)
            esc_path = session / 'escalation.json'
            esc_path.write_text(json.dumps({
                'version': 1, 'family': 'hydrogen', 'seat': 'escalate-hydrogen',
                'lab': 'google', 'adapter': 'agy', 'model': 'gemini-4-hydrogen-high',
                'effort': 'high', 'extra': False,
            }), encoding='utf-8')
            with self.assertRaises(ValueError):
                wh_agy.read_escalation(esc_path)
            with self.assertRaises(ValueError):
                wh_agy.escalate(session, 'codex-sol')
            with self.assertRaises(ValueError):
                wh_agy.advance(session)

        # Evidence replacement helpers refuse agy/hydrogen/neon off REVIEW_COUNCIL_HOST=agy.
        ev = load('rev_evidence_under_test', SCRIPTS / 'rev-evidence.py')
        ev_sess = self.root / 'ev-session'
        ev_sess.mkdir()
        (ev_sess / 'workhorse.json').write_text(json.dumps(rec), encoding='utf-8')
        (ev_sess / 'panel-request.json').write_text(json.dumps({
            'version': 1, 'host': 'agy',
            'chain': ['hydrogen', 'luna', 'sonnet', 'sol', 'neon', 'opus'],
        }), encoding='utf-8')
        repair_manifest = {
            'phase': 'repair',
            'assignments': {'escalate-neon': {'adapter': 'agy'}},
            'replacement_executor': {
                'seat': 'escalate-neon', 'family': 'neon', 'adapter': 'agy',
                'model': 'gemini-4-neon-high', 'effort': 'high', 'extra': False,
            },
        }
        with patch.dict(os.environ, {'REVIEW_COUNCIL_HOST': 'agy'}, clear=False):
            self.assertEqual(
                ev.session_chain(ev_sess),
                ('hydrogen', 'luna', 'sonnet', 'sol', 'neon', 'opus'),
            )
            self.assertEqual(ev.replacement_executor_row(repair_manifest)['family'], 'neon')
        with patch.dict(os.environ, {'REVIEW_COUNCIL_HOST': 'claude'}, clear=False):
            self.assertEqual(ev.session_chain(ev_sess), ('luna', 'sonnet', 'sol', 'opus'))
            with self.assertRaises(ValueError):
                ev.replacement_executor_row(repair_manifest)

    def test_seat_adapter_read_audit_and_usage_end_to_end(self):
        usage = load('usage_under_test', LIB / 'usage.py')
        repo = self.root / 'repo'
        repo.mkdir()
        session = self.root / 'session'
        session.mkdir()
        target_file = repo / 'hello.txt'
        target_file.write_bytes(b'line one\nline two\n')
        prompt = session / 'r1-agy-1.prompt.md'
        # >130 KiB prompt verifies stdin stream-json delivery avoids Linux MAX_ARG_STRLEN E2BIG.
        large_pad = 'x' * (135 * 1024)
        prompt.write_text(f'Review this repo.\n{large_pad}\n', encoding='utf-8')
        roster = {
            'seats': [{
                'seat': 'agy-1', 'lab': 'google', 'adapter': 'agy',
                'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False,
            }]
        }
        (session / 'roster.json').write_text(json.dumps(roster), encoding='utf-8')

        findings = {
            'summary': 'No actionable issues found.',
            'findings': [],
        }
        stream_events = [
            {'event': 'init', 'init': {'model': 'gemini-4-hydrogen-xhigh'}},
            {'event': 'step_update', 'step_update': {
                'step_type': 'tool', 'step_index': 2, 'state': 'ACTIVE',
                'tool_name': 'run_command',
                'tool_info': {'name': 'run_command',
                              'parameters': {'CommandLine': f"sed -n '1,2p' {target_file}"}},
            }},
            {'event': 'step_update', 'step_update': {
                'step_type': 'tool', 'step_index': 2, 'state': 'DONE',
                'tool_name': 'run_command',
                'tool_info': {
                    'name': 'run_command',
                    'parameters': {'CommandLine': f"sed -n '1,2p' {target_file}"},
                    'output': 'Created At: 2026-11-23T00:00:00Z\nCompleted At: 2026-11-23T00:00:01Z\nCommand exited with code 0.\n\nCommand output:\nline one\r\nline two\r\n',
                },
            }},
            {'event': 'result', 'result': {
                'status': 'SUCCESS',
                'structured_output': findings,
                'num_turns': 1,
                'usage': {
                    'input_tokens': 1200,
                    'output_tokens': 80,
                    'thinking_tokens': 30,
                    'cache_read_tokens': 400,
                    'total_tokens': 1280,
                },
            }},
        ]
        bindir = self.root / 'seat-bin'
        bindir.mkdir()
        events_json = self.root / 'events.json'
        events_json.write_text('\n'.join(json.dumps(ev) for ev in stream_events) + '\n', encoding='utf-8')
        captured_argv = self.root / 'agy-argv.txt'
        captured_stdin = self.root / 'agy-stdin.jsonl'
        fake_agy = bindir / 'agy'
        fake_agy.write_text(
            '#!/bin/bash\n'
            f'printf "%s\\n" "$@" > "{captured_argv}"\n'
            f'cat > "{captured_stdin}"\n'
            f'cat "{events_json}"\n',
            encoding='utf-8',
        )
        fake_agy.chmod(0o755)

        seat_env = dict(
            self.clean_env,
            PATH=str(bindir) + os.pathsep + os.environ.get('PATH', ''),
            REVIEW_COUNCIL_HOST='agy',
        )
        run = subprocess.run(
            [str(SCRIPTS / 'rev-seat.sh'), 'agy-1', str(session), '1', str(prompt)],
            cwd=repo, env=seat_env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        argv_lines = captured_argv.read_text(encoding='utf-8').splitlines()
        self.assertIn('--input-format', argv_lines)
        self.assertIn('stream-json', argv_lines)
        self.assertFalse(any(a.startswith('--print') for a in argv_lines))
        stdin_doc = json.loads(captured_stdin.read_text(encoding='utf-8').strip())
        self.assertEqual(stdin_doc['event'], 'user')
        self.assertEqual(stdin_doc['message']['content'], prompt.read_text(encoding='utf-8'))
        self.assertEqual((session / 'r1-agy-1.exit').read_text().strip(), '0')
        self.assertEqual(json.loads((session / 'r1-agy-1.json').read_text()), findings)
        self.assertIn('tool_call run_command:', (session / 'r1-agy-1.log').read_text())

        audit_doc = json.loads((session / 'r1-agy-1.read-audit.json').read_text())
        self.assertEqual(audit_doc['status'], 'valid')

        # Verify read audit handles CRLF repository files and leaves non-run_command outputs raw.
        rra = load('review_read_audit_under_test', LIB / 'review-read-audit.py')
        calls = rra.extract_calls('agy', stream_events[1])
        self.assertEqual(calls[0][1], 'run_command')
        self.assertEqual(calls[0][2]['command'], f"sed -n '1,2p' {target_file}")
        outputs = rra.extract_outputs('agy', stream_events[2])
        self.assertEqual(outputs[0][0], calls[0][0])
        self.assertTrue(outputs[0][1])
        self.assertEqual(outputs[0][2].encode('utf-8'), target_file.read_bytes())

        crlf_file = repo / 'crlf.ts'
        crlf_file.write_bytes(b'const a = 1;\r\nconst b = 2;\r\n')
        self.assertTrue(rra.delivered_matches(
            'agy', 'run_command', outputs[0][2], crlf_file, 1, 2) is False)
        self.assertTrue(rra.delivered_matches(
            'agy', 'run_command', 'const a = 1;\nconst b = 2;\n', crlf_file, 1, 2))
        self.assertFalse(rra.delivered_matches(
            'codex', 'command_execution', 'const a = 1;\nconst b = 2;\n', crlf_file, 1, 2))
        raw_non_cmd = rra.extract_outputs('agy', {'event': 'step_update', 'step_update': {
            'step_type': 'tool', 'step_index': 9, 'state': 'DONE',
            'tool_info': {'name': 'custom_tool', 'output': 'a\r\nb\r\n'},
        }})
        self.assertEqual(raw_non_cmd[0][2], 'a\r\nb\r\n')

        # Verify stream-summary tolerates non-object nested fields on agy events.
        malformed_out = self.root / 'malformed-out.json'
        sum_proc = subprocess.run(
            ['python3', str(LIB / 'stream-summary.py'), 'agy', str(malformed_out)],
            input='\n'.join([
                json.dumps({'event': 'init', 'init': 'bad'}),
                json.dumps({'event': 'step_update', 'step_update': []}),
                json.dumps({'event': 'step_update', 'step_update': {
                    'step_type': 'tool', 'state': 'ACTIVE', 'tool_info': 'bad',
                }}),
                json.dumps({'event': 'result', 'result': []}),
            ]) + '\n',
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(sum_proc.returncode, 0, sum_proc.stderr)

        # Verify stack.sh refuses REVIEW_COUNCIL_HOST=agy in a repo checkout without an agy skill.
        stack_repo = self.root / 'stack-repo'
        stack_repo.mkdir()
        subprocess.run(['git', '-C', str(stack_repo), 'init', '-q'], check=True)
        subprocess.run(['git', '-C', str(stack_repo), 'config', 'user.email', 'test@example.invalid'], check=True)
        subprocess.run(['git', '-C', str(stack_repo), 'config', 'user.name', 'Test'], check=True)
        (stack_repo / 'f.txt').write_text('one\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(stack_repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(stack_repo), 'commit', '-qm', 'init'], check=True)
        stack_cfg = self.root / 'stack-config.sh'
        stack_cfg.write_text(
            'PASSES=1\nMAX_ATTEMPTS=1\n'
            f'legs() {{ run_leg "{stack_repo}" 1 leg1 "check"; }}\n',
            encoding='utf-8',
        )
        agy_roster_bin = self.root / 'stack-agy-bin'
        agy_roster_bin.mkdir()
        (agy_roster_bin / 'agy').write_text(
            '#!/bin/bash\n'
            '[ "${1:-}" = models ] && { printf "gemini-4-hydrogen-xhigh  H\\n"; exit 0; }\n'
            'echo "1.5.15"\n',
            encoding='utf-8',
        )
        (agy_roster_bin / 'agy').chmod(0o755)
        agy_cfg = self.root / 'stack-agy-cfg.json'
        agy_cfg.write_text(json.dumps({'min_labs': 1, 'claude_seats': 0, 'extras': False}), encoding='utf-8')
        stack_env = dict(
            self.clean_env,
            PATH=str(agy_roster_bin) + ':/usr/bin:/bin',
            REVIEW_COUNCIL_HOST='agy',
            REVIEW_COUNCIL_CONFIG=str(agy_cfg),
            REV_STACK_FOREGROUND='1',
            ROOT=str(self.root / 'stack-root'),
            LOG=str(self.root / 'stack.log'),
        )
        stack_res = subprocess.run(
            [str(SCRIPTS / 'stack.sh'), str(stack_cfg)],
            cwd=repo, env=stack_env, capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(stack_res.returncode, 0)
        self.assertIn('missing Antigravity rev skill', stack_res.stdout + stack_res.stderr)

        # Verify usage extraction from agy stream.
        item, _msgs, _ids, invalid = usage.read_stream(session / 'r1-agy-1.stream.ndjson', 'agy')
        self.assertEqual(invalid, [])
        self.assertEqual(item['provider'], 'agy')
        self.assertEqual(item['input_tokens'], 1200)
        self.assertEqual(item['output_tokens'], 80)
        self.assertEqual(item['reasoning_output_tokens'], 30)
        self.assertEqual(item['cache_read_input_tokens'], 400)

        # Google ToC check: running an agy seat off agy host is refused.
        refused = subprocess.run(
            [str(SCRIPTS / 'rev-seat.sh'), 'agy-1', str(session), '2', str(prompt)],
            cwd=repo, env=dict(seat_env, REVIEW_COUNCIL_HOST='claude'),
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(refused.returncode, 1)
        self.assertIn('REVIEW_COUNCIL_HOST=agy', refused.stderr)

    def _init_git_repo(self, repo_dir):
        repo_dir.mkdir(parents=True, exist_ok=True)
        for cmd in (
            ['init', '-q'],
            ['config', 'user.name', 'Test'],
            ['config', 'user.email', 'test@example.invalid'],
            ['config', 'commit.gpgsign', 'false'],
            ['config', 'core.hooksPath', str(self.root / 'no-hooks')],
        ):
            subprocess.run(['git', '-C', str(repo_dir), *cmd], check=True)

    def _prepare_evidence_fixture(self, name, seats, *, patch_bytes_target=20000,
                                  patch_chunks_mode='auto', short_lines=False):
        repo = self.root / (name + '-repo')
        session = self.root / (name + '-session')
        session.mkdir(parents=True, exist_ok=True)
        self._init_git_repo(repo)
        (repo / 'src').mkdir()

        # Build a large changed file (~patch_bytes_target) with an unchanged >10 KiB declaration
        # body on fn00 (so it cannot be patch-proven and produces required source segments) plus
        # callers whose windows exceed 8 KiB so source-context shards pack up to the 8 KiB cap.
        decls = []
        if short_lines:
            # 80 modified lines -> ~167 diff lines (1 window <= 240 lines) and ~12 KiB bytes
            # (~13.6 KiB visible): >8 KiB triggers chunks for agy, <=30 KiB stays windows for codex.
            decls.append('def fn00():\n' + ''.join(
                f'    v{i:02d} = "val_{i:02d}_{"x" * 58}"\n' for i in range(80)
            ) + '    return v00\n')
        else:
            fn0_lines = ['def fn00():'] + [
                f'    _u{i:02d} = "{"u" * 190}"' for i in range(52)
            ] + ['    return "old"']
            decls.append('\n'.join(fn0_lines) + '\n')
            for i in range(1, 7):
                decls.append(f'def fn{i:02d}():\n    return "{"a" * (max(100, patch_bytes_target // 6))}"\n')
        (repo / 'src/lib.py').write_text('\n'.join(decls), encoding='utf-8')
        # Add callers whose 5-line call-site windows total > 8 KiB.
        for i in range(6):
            pad = 'c' * 1900
            (repo / f'src/caller{i}.py').write_text(
                f'from src.lib import fn00\n'
                f'def caller{i}():\n    _pad = "{pad}"\n    return fn00()\n',
                encoding='utf-8',
            )

        subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'base'], check=True)
        base = subprocess.run(
            ['git', '-C', str(repo), 'rev-parse', 'HEAD'],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

        # Modify lib.py so its diff exceeds patch_bytes_target while keeping fn00's body unchanged.
        if short_lines:
            updated = '\n'.join(decls).replace('"val_', '"new_')
        else:
            updated_decls = [decls[0].replace('    return "old"', '    return "new"')]
            for i in range(1, 7):
                updated_decls.append(
                    f'def fn{i:02d}():\n    return "{"z" * (max(100, patch_bytes_target // 6))}"\n'
                )
            updated = '\n'.join(updated_decls)
        (repo / 'src/lib.py').write_text(updated, encoding='utf-8')

        (session / 'scope.env').write_text(
            f'REV_BASE={shlex.quote(base)}\n'
            f'REV_ROOT={shlex.quote(str(repo))}\n'
            'REV_SCOPE=branch\n',
            encoding='utf-8',
        )
        (session / 'files.txt').write_text('src/lib.py\n', encoding='utf-8')
        (session / 'untracked.txt').write_text('', encoding='utf-8')
        (session / 'roster.json').write_text(json.dumps({'seats': seats}), encoding='utf-8')

        env = dict(
            self.clean_env,
            REV_PATCH_CHUNKS=patch_chunks_mode,
            REV_SOURCE_CONTEXT='1',
        )
        prep = subprocess.run(
            [sys.executable, str(SCRIPTS / 'rev-evidence.py'), 'prepare',
             str(session), '1', '--phase', 'discovery', '--full-seat', seats[0]['seat']],
            env=env, capture_output=True, text=True, check=False, timeout=60,
        )
        self.assertEqual(prep.returncode, 0, prep.stdout + prep.stderr)
        ev = load('rev_evidence_agy_cap', SCRIPTS / 'rev-evidence.py')
        manifest_path = session / 'r1-evidence.manifest.json'
        manifest = ev.expand_manifest(json.loads(manifest_path.read_text(encoding='utf-8')))
        return ev, repo, session, manifest_path, manifest, env

    def test_agy_evidence_artifacts_capped_at_8kib_and_mixed_panel_isolated(self):
        # 1) Pure agy panel with >16 KiB patch, >10 KiB source context, and >10 KiB required range.
        agy_seats = [
            {'seat': f'agy-{i}', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False}
            for i in range(1, 4)
        ]
        ev, repo, session, manifest_path, manifest, _ = self._prepare_evidence_fixture(
            'agy-only', agy_seats, patch_bytes_target=20000, patch_chunks_mode='auto',
        )
        ev.validated_manifest(manifest_path, fresh=True)
        assignment = manifest['assignments']['agy-1']
        self.assertEqual(assignment['patch_read_mode'], 'chunks')
        patch_set = manifest['patch_sets'][assignment['patch_set']]
        self.assertGreater(len(patch_set['chunks']), 2)
        reconstructed = b''
        for chunk in patch_set['chunks']:
            self.assertLessEqual(chunk['bytes'], 8192)
            self.assertLessEqual(chunk['predicted_visible_bytes'], 8192)
            reconstructed += (session / chunk['artifact']).read_bytes()
        self.assertEqual(reconstructed, Path(assignment['patch']).read_bytes())

        ctx = manifest['source_context']['seats']['agy-1']
        self.assertEqual(manifest['source_context']['max_shard_bytes'], 16384)
        self.assertTrue(ctx['shards'])
        for shard in ctx['shards']:
            self.assertLessEqual(shard['bytes'], 8192)
            self.assertLessEqual(shard['predicted_visible_bytes'], 8192)
        segmented = [row for row in ctx['required_source_ranges'] if row['segments']]
        self.assertTrue(segmented)
        for row in segmented:
            for seg in row['segments']:
                self.assertLessEqual(seg['predicted_visible_bytes'], 8192)

        # 2) Mixed panel (agy + codex) on the same patch keeps distinct patch_sets and validates.
        mixed_seats = [
            {'seat': 'agy-1', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False},
            {'seat': 'codex-luna', 'lab': 'openai', 'adapter': 'codex',
             'model': 'gpt-5.6-luna', 'effort': 'xhigh', 'extra': False},
            {'seat': 'agy-2', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False},
        ]
        ev_mix, _repo_m, sess_m, mpath_m, man_mix, _ = self._prepare_evidence_fixture(
            'mixed', mixed_seats, patch_bytes_target=20000, patch_chunks_mode='auto',
        )
        ev_mix.validated_manifest(mpath_m, fresh=True)
        agy_set_id = man_mix['assignments']['agy-1']['patch_set']
        codex_set_id = man_mix['assignments']['codex-luna']['patch_set']
        self.assertNotEqual(agy_set_id, codex_set_id)
        for chunk in man_mix['patch_sets'][agy_set_id]['chunks']:
            self.assertLessEqual(chunk['predicted_visible_bytes'], 8192)
        self.assertTrue(any(
            chunk['bytes'] > 8192 for chunk in man_mix['patch_sets'][codex_set_id]['chunks']
        ))

        # Validation must reject a mixed-adapter patch set or oversized agy shard.
        bad_mix = json.loads(mpath_m.read_text(encoding='utf-8'))
        for agy_seat in ('agy-1', 'agy-2'):
            bad_mix['assignments'][agy_seat]['patch_set'] = codex_set_id
            bad_mix['assignments'][agy_seat]['patch_read_mode'] = (
                man_mix['patch_sets'][codex_set_id]['read_mode']
            )
        with self.assertRaisesRegex(ValueError, 'incompatible adapter limits'):
            ev_mix.validate_patch_sets(sess_m, bad_mix, set())

        bad_shard = ev_mix.expand_manifest(json.loads(mpath_m.read_text(encoding='utf-8')))
        bad_shard['source_context']['seats']['agy-1']['shards'][0]['predicted_visible_bytes'] = 9000
        bad_evidence = json.loads((sess_m / 'r1-evidence.json').read_text(encoding='utf-8'))
        bad_evidence['source_context'] = bad_shard['source_context']
        with self.assertRaisesRegex(ValueError, 'shard bounds'):
            ev_mix.validate_source_context(sess_m, bad_shard, bad_evidence)

    def test_agy_auto_patch_mode_switches_to_chunks_past_8kib_window(self):
        # ~12 KiB in <240 short lines: agy switches to chunks, codex stays in windows.
        seats = [
            {'seat': 'agy-1', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False},
            {'seat': 'codex-luna', 'lab': 'openai', 'adapter': 'codex',
             'model': 'gpt-5.6-luna', 'effort': 'xhigh', 'extra': False},
            {'seat': 'agy-2', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False},
        ]
        ev, _repo, _session, mpath, manifest, _ = self._prepare_evidence_fixture(
            'auto-mode', seats, patch_chunks_mode='auto', short_lines=True,
        )
        ev.validated_manifest(mpath, fresh=True)
        self.assertEqual(manifest['assignments']['agy-1']['patch_read_mode'], 'chunks')
        self.assertEqual(manifest['assignments']['codex-luna']['patch_read_mode'], 'windows')

    def test_agy_read_audit_valid_under_10kib_run_command_truncation(self):
        agy_seats = [
            {'seat': f'agy-{i}', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False}
            for i in range(1, 4)
        ]
        _ev, repo, session, manifest_path, manifest, env = self._prepare_evidence_fixture(
            'e2e-trunc', agy_seats, patch_bytes_target=20000, patch_chunks_mode='auto',
        )
        prompt_out = subprocess.run(
            [str(SCRIPTS / 'rev-prompt.sh'), str(session), '1', 'agy-1',
             manifest['assignments']['agy-1']['bundle'], 'check truncation cap',
             '--evidence', str(manifest_path)],
            env=env, capture_output=True, text=True, check=False, timeout=60,
        )
        self.assertEqual(prompt_out.returncode, 0, prompt_out.stdout + prompt_out.stderr)
        prompt_path = session / 'r1-agy-1.prompt.md'
        self.assertIn('below ~8 KiB', prompt_path.read_text(encoding='utf-8'))

        # Simulate agy run_command truncating any formatted output over 10,240 bytes.
        ctx = manifest['source_context']['seats']['agy-1']
        patch_chunks = manifest['patch_sets'][manifest['assignments']['agy-1']['patch_set']]['chunks']
        evidence_md = session / 'r1-evidence.md'
        read_cmds = (
            [f'cat -- {shlex.quote(str(session / c["artifact"]))}' for c in patch_chunks]
            + [f'cat -- {shlex.quote(str(session / s["artifact"]))}' for s in ctx['shards']]
            + [f'cat -- {shlex.quote(str(session / seg["artifact"]))}'
               for row in ctx['required_source_ranges'] for seg in row['segments']]
            + [f'cat -- {shlex.quote(str(evidence_md))}']
        )
        if ctx['source_read_required']:
            target = (manifest.get('task_capacity', {}).get('seats', {})
                      .get('agy-1', {}).get('repository_source_target'))
            if target is not None:
                start = target['line_start']
                while start <= target['line_end']:
                    end = min(target['line_end'], start + 29)
                    read_cmds.append(f"sed -n '{start},{end}p' {shlex.quote(target['path'])}")
                    start = end + 1
            else:
                read_cmds.append("sed -n '1,20p' 'src/lib.py'")

        events = [{'event': 'init', 'init': {'model': 'gemini-4-hydrogen-xhigh'}}]
        for idx, cmd in enumerate(read_cmds, 1):
            events.append({'event': 'step_update', 'step_update': {
                'step_type': 'tool', 'step_index': idx, 'state': 'ACTIVE',
                'tool_name': 'run_command',
                'tool_info': {'name': 'run_command', 'parameters': {'CommandLine': cmd}},
            }})
            raw_out = subprocess.run(
                cmd, shell=True, cwd=repo, capture_output=True, text=True, check=True,
            ).stdout.replace('\n', '\r\n')
            formatted = (
                'Created At: 2026-11-23T00:00:00Z\n'
                'Completed At: 2026-11-23T00:00:01Z\n'
                'Command exited with code 0.\n\n'
                f'Command output:\n{raw_out}'
            )
            if len(formatted.encode('utf-8')) > 10240:
                formatted = "The tool's output was truncated due to being too long.\n" + formatted[:500]
            events.append({'event': 'step_update', 'step_update': {
                'step_type': 'tool', 'step_index': idx, 'state': 'DONE',
                'tool_name': 'run_command',
                'tool_info': {
                    'name': 'run_command',
                    'parameters': {'CommandLine': cmd},
                    'output': formatted,
                },
            }})
        events.append({'event': 'result', 'result': {
            'status': 'SUCCESS',
            'structured_output': {'summary': 'No actionable issues found.', 'findings': []},
            'num_turns': len(read_cmds),
            'usage': {'input_tokens': 1000, 'output_tokens': 50, 'total_tokens': 1050},
        }})

        bindir = self.root / 'e2e-agy-bin'
        bindir.mkdir()
        ev_file = self.root / 'e2e-events.jsonl'
        ev_file.write_text('\n'.join(json.dumps(e) for e in events) + '\n', encoding='utf-8')
        fake_agy = bindir / 'agy'
        fake_agy.write_text(f'#!/bin/bash\ncat >/dev/null\ncat "{ev_file}"\n', encoding='utf-8')
        fake_agy.chmod(0o755)

        seat_env = dict(
            self.clean_env,
            PATH=str(bindir) + os.pathsep + os.environ.get('PATH', ''),
            REVIEW_COUNCIL_HOST='agy',
        )
        run = subprocess.run(
            [str(SCRIPTS / 'rev-seat.sh'), 'agy-1', str(session), '1', str(prompt_path)],
            cwd=repo, env=seat_env, capture_output=True, text=True, check=False, timeout=60,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        audit = json.loads((session / 'r1-agy-1.read-audit.json').read_text(encoding='utf-8'))
        self.assertEqual(audit['status'], 'valid', audit)

    def _prepare_nav_overflow_fixture(self, name, seats, *, caller_count=14, include_crlf=False):
        repo = self.root / (name + '-repo')
        session = self.root / (name + '-session')
        session.mkdir(parents=True, exist_ok=True)
        self._init_git_repo(repo)
        (repo / 'src').mkdir()
        (repo / 'tests').mkdir()

        fn0_lines = ['def fn00():'] + [
            f'    _u{i:02d} = "{"u" * 190}"' for i in range(52)
        ] + ['    return "old"']
        decls = ['\n'.join(fn0_lines) + '\n']
        for i in range(1, 12):
            decls.append(
                f'def fn{i:02d}_{"n" * 40}():\n    return "{"a" * 300}"\n'
            )
        (repo / 'src/lib.py').write_text('\n'.join(decls), encoding='utf-8')
        for i in range(caller_count):
            (repo / f'src/caller_{i:02d}_{"c" * 32}.py').write_text(
                f'from src.lib import fn00\n'
                f'def caller_{i:02d}():\n    _pad = "{"c" * 1900}"\n    return fn00()\n',
                encoding='utf-8',
            )
        for i in range(12):
            (repo / f'tests/test_nav_{i:02d}_{"t" * 32}.py').write_text(
                f'from src.lib import fn00\n'
                f'def test_nav_{i:02d}():\n    assert fn00() is not None\n',
                encoding='utf-8',
            )
        scripts = {f'test:gate:{i:02d}': f'echo {"g" * 420}' for i in range(12)}
        (repo / 'package.json').write_text(json.dumps({'scripts': scripts}, indent=2) + '\n',
                                           encoding='utf-8')
        if include_crlf:
            (repo / 'src/crlf_ref.py').write_bytes(
                b'def crlf_helper():\r\n    return "crlf-ok"\r\n'
            )

        subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'base'], check=True)
        base = subprocess.run(
            ['git', '-C', str(repo), 'rev-parse', 'HEAD'],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

        updated_decls = [decls[0].replace('    return "old"', '    return "new"')]
        for i in range(1, 12):
            updated_decls.append(
                f'def fn{i:02d}_{"n" * 40}():\n    return "{"z" * 300}"\n'
            )
        (repo / 'src/lib.py').write_text('\n'.join(updated_decls), encoding='utf-8')
        if include_crlf:
            (repo / 'src/crlf_ref.py').write_bytes(
                b'def crlf_helper():\r\n    return "crlf-updated"\r\n'
            )

        (session / 'scope.env').write_text(
            f'REV_BASE={shlex.quote(base)}\n'
            f'REV_ROOT={shlex.quote(str(repo))}\n'
            'REV_SCOPE=branch\n',
            encoding='utf-8',
        )
        changed_files = 'src/lib.py\nsrc/crlf_ref.py\n' if include_crlf else 'src/lib.py\n'
        (session / 'files.txt').write_text(changed_files, encoding='utf-8')
        (session / 'untracked.txt').write_text('', encoding='utf-8')
        (session / 'roster.json').write_text(json.dumps({'seats': seats}), encoding='utf-8')

        env = dict(self.clean_env, REV_PATCH_CHUNKS='auto', REV_SOURCE_CONTEXT='1')
        prep = subprocess.run(
            [sys.executable, str(SCRIPTS / 'rev-evidence.py'), 'prepare',
             str(session), '1', '--phase', 'discovery', '--full-seat', seats[0]['seat']],
            env=env, capture_output=True, text=True, check=False, timeout=60,
        )
        self.assertEqual(prep.returncode, 0, prep.stdout + prep.stderr)
        ev = load('rev_evidence_nav_cap', SCRIPTS / 'rev-evidence.py')
        manifest_path = session / 'r1-evidence.manifest.json'
        manifest = ev.expand_manifest(json.loads(manifest_path.read_text(encoding='utf-8')))
        return ev, repo, session, manifest_path, manifest, env

    def _build_seat_read_commands(self, session, manifest, seat, *, index_cmds=None):
        ctx = manifest['source_context']['seats'][seat]
        patch_set = manifest['patch_sets'][manifest['assignments'][seat]['patch_set']]
        if patch_set['read_mode'] == 'chunks':
            patch_cmds = [
                f'cat -- {shlex.quote(str(session / c["artifact"]))}'
                for c in patch_set['chunks']
            ]
        else:
            lines = manifest['assignments'][seat]['patch_lines']
            patch_path = manifest['assignments'][seat]['patch']
            patch_cmds = []
            start = 1
            while start <= lines:
                end = min(lines, start + 239)
                patch_cmds.append(f"sed -n '{start},{end}p' {shlex.quote(patch_path)}")
                start = end + 1
        packet_cmds = [f'cat -- {shlex.quote(str(session / s["artifact"]))}' for s in ctx['shards']]
        seg_cmds = [
            f'cat -- {shlex.quote(str(session / seg["artifact"]))}'
            for row in ctx['required_source_ranges'] for seg in row['segments']
        ]
        evidence_md = session / 'r1-evidence.md'
        if index_cmds is None:
            index_cmds = [f'cat -- {shlex.quote(str(evidence_md))}']
        target_cmds = []
        if ctx['source_read_required']:
            target = (manifest.get('task_capacity', {}).get('seats', {})
                      .get(seat, {}).get('repository_source_target'))
            if target is not None:
                start = target['line_start']
                while start <= target['line_end']:
                    end = min(target['line_end'], start + 29)
                    target_cmds.append(f"sed -n '{start},{end}p' {shlex.quote(target['path'])}")
                    start = end + 1
            else:
                target_cmds.append("sed -n '1,20p' 'src/lib.py'")
        return patch_cmds + packet_cmds + seg_cmds, index_cmds, target_cmds

    def _build_fake_agy_events(self, repo, read_cmds, *, simulate_truncation=False,
                               output_transform=None):
        events = [{'event': 'init', 'init': {'model': 'gemini-4-hydrogen-xhigh'}}]
        for idx, cmd in enumerate(read_cmds, 1):
            events.append({'event': 'step_update', 'step_update': {
                'step_type': 'tool', 'step_index': idx, 'state': 'ACTIVE',
                'tool_name': 'run_command',
                'tool_info': {'name': 'run_command', 'parameters': {'CommandLine': cmd}},
            }})
            raw_out = subprocess.run(
                cmd, shell=True, cwd=repo, capture_output=True, check=True,
            ).stdout.decode('utf-8', errors='replace')
            formatted = re.sub(
                r'(?<!\r)\n',
                '\r\n',
                'Created At: 2026-11-23T00:00:00Z\n'
                'Completed At: 2026-11-23T00:00:01Z\n'
                'Command exited with code 0.\n\n'
                f'Command output:\n{raw_out}',
            )
            if output_transform is not None:
                formatted = output_transform(idx, cmd, formatted)
            if simulate_truncation and len(formatted.encode('utf-8')) > 10240:
                formatted = (
                    "The tool's output was truncated due to being too long.\n"
                    + formatted[:500]
                )
            events.append({'event': 'step_update', 'step_update': {
                'step_type': 'tool', 'step_index': idx, 'state': 'DONE',
                'tool_name': 'run_command',
                'tool_info': {
                    'name': 'run_command',
                    'parameters': {'CommandLine': cmd},
                    'output': formatted,
                },
            }})
        events.append({'event': 'result', 'result': {
            'status': 'SUCCESS',
            'structured_output': {'summary': 'No actionable issues found.', 'findings': []},
            'num_turns': len(read_cmds),
            'usage': {'input_tokens': 1000, 'output_tokens': 50, 'total_tokens': 1050},
        }})
        return events

    def _run_fake_agy_seat(self, name, repo, session, prompt_path, seat, read_cmds,
                           *, simulate_truncation=False, output_transform=None):
        events = self._build_fake_agy_events(
            repo, read_cmds, simulate_truncation=simulate_truncation,
            output_transform=output_transform,
        )
        bindir = self.root / f'{name}-bin'
        bindir.mkdir(exist_ok=True)
        ev_file = self.root / f'{name}-events.jsonl'
        ev_file.write_text('\n'.join(json.dumps(e) for e in events) + '\n', encoding='utf-8')
        fake_agy = bindir / 'agy'
        fake_agy.write_text(f'#!/bin/bash\ncat >/dev/null\ncat "{ev_file}"\n', encoding='utf-8')
        fake_agy.chmod(0o755)
        seat_env = dict(
            self.clean_env,
            PATH=str(bindir) + os.pathsep + os.environ.get('PATH', ''),
            REVIEW_COUNCIL_HOST='agy',
        )
        return subprocess.run(
            [str(SCRIPTS / 'rev-seat.sh'), seat, str(session), '1', str(prompt_path)],
            cwd=repo, env=seat_env, capture_output=True, text=True, check=False, timeout=60,
        )

    def _audit_fake_agy_stream(self, rra, tag, repo, session, prompt_path, seat, result_file,
                               read_cmds, *, simulate_truncation=False, output_transform=None):
        events = self._build_fake_agy_events(
            repo, read_cmds, simulate_truncation=simulate_truncation,
            output_transform=output_transform,
        )
        stream = self.root / f'{tag}.ndjson'
        stream.write_text('\n'.join(json.dumps(e) for e in events) + '\n', encoding='utf-8')
        doc, _ = rra.assessed(types.SimpleNamespace(
            adapter='agy', raw=str(stream), prompt=str(prompt_path),
            root=str(repo), session=str(session), deps=None, seat=seat,
            result=str(result_file), out=str(self.root / f'{tag}-audit.json'),
        ))
        return doc, {r['code'] for r in doc['violations'] + doc['advisories']}

    def test_agy_navigation_index_capped_at_8kib_and_non_agy_keeps_16kib(self):
        codex_seats = [
            {'seat': f'codex-{i}', 'lab': 'openai', 'adapter': 'codex',
             'model': 'gpt-5.6-luna', 'effort': 'xhigh', 'extra': False}
            for i in range(1, 4)
        ]
        ev_c, _repo_c, sess_c, mpath_c, _man_c, _env_c = self._prepare_nav_overflow_fixture(
            'nav-codex', codex_seats,
        )
        ev_c.validated_manifest(mpath_c, fresh=True)
        codex_index = (sess_c / 'r1-evidence.md').read_bytes()
        self.assertGreater(len(codex_index), 10240)
        self.assertLessEqual(len(codex_index), 16384)

        agy_seats = [
            {'seat': f'agy-{i}', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False}
            for i in range(1, 4)
        ]
        ev_a, repo_a, sess_a, mpath_a, man_a, env_a = self._prepare_nav_overflow_fixture(
            'nav-agy', agy_seats,
        )
        ev_a.validated_manifest(mpath_a, fresh=True)
        agy_index = (sess_a / 'r1-evidence.md').read_bytes()
        self.assertLessEqual(len(agy_index), 8192)
        agy_text = agy_index.decode('utf-8')
        for heading in (
            'Symbols:', 'Call Sites:', 'Related Tests:',
            'Unresolved or aliased import proof obligations:', 'Gates:', 'Instructions:',
        ):
            self.assertIn(heading, agy_text)
        self.assertEqual(agy_text.count('Omitted:'), 6)
        self.assertEqual(agy_text.count('complete list SHA-256:'), 6)
        self.assertIn('Lexical navigation only; open source to prove findings.', agy_text)

        mixed_seats = [
            {'seat': 'agy-1', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False},
            {'seat': 'codex-luna', 'lab': 'openai', 'adapter': 'codex',
             'model': 'gpt-5.6-luna', 'effort': 'xhigh', 'extra': False},
            {'seat': 'agy-2', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False},
        ]
        ev_m, _repo_m, sess_m, mpath_m, _man_m, _env_m = self._prepare_nav_overflow_fixture(
            'nav-mixed', mixed_seats,
        )
        ev_m.validated_manifest(mpath_m, fresh=True)
        self.assertLessEqual(len((sess_m / 'r1-evidence.md').read_bytes()), 8192)

        # Simulated 10,240-byte run_command truncation passes end-to-end on the capped agy index.
        prompt_res = subprocess.run(
            [str(SCRIPTS / 'rev-prompt.sh'), str(sess_a), '1', 'agy-1',
             man_a['assignments']['agy-1']['bundle'], 'check nav cap',
             '--evidence', str(mpath_a)],
            env=env_a, capture_output=True, text=True, check=False, timeout=60,
        )
        self.assertEqual(prompt_res.returncode, 0, prompt_res.stdout + prompt_res.stderr)
        prompt_path = sess_a / 'r1-agy-1.prompt.md'
        pre_cmds, idx_cmds, post_cmds = self._build_seat_read_commands(sess_a, man_a, 'agy-1')
        run = self._run_fake_agy_seat(
            'nav-agy', repo_a, sess_a, prompt_path, 'agy-1',
            pre_cmds + idx_cmds + post_cmds, simulate_truncation=True,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        audit = json.loads((sess_a / 'r1-agy-1.read-audit.json').read_text(encoding='utf-8'))
        self.assertEqual(audit['status'], 'valid', audit)

        # Fixed metadata alone exceeding the 8 KiB agy cap must fail closed.
        oversized = {
            section: [] for section in (
                'symbols', 'call_sites', 'related_tests',
                'unresolved_imports', 'gates', 'instructions',
            )
        }
        oversized['limitations'] = ['x' * 8500]
        with self.assertRaisesRegex(ValueError, 'navigation packet exceeds byte limit'):
            ev_a.markdown(oversized, Path('facts.json'), total_limit=ev_a.AGY_NAVIGATION_TOTAL_LIMIT)

    def test_agy_pty_crcrlf_line_endings_pass_byte_exact_audit(self):
        agy_seats = [
            {'seat': f'agy-{i}', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False}
            for i in range(1, 4)
        ]
        _ev, repo, session, manifest_path, manifest, env = self._prepare_nav_overflow_fixture(
            'crcrlf', agy_seats, include_crlf=True,
        )
        prompt_res = subprocess.run(
            [str(SCRIPTS / 'rev-prompt.sh'), str(session), '1', 'agy-1',
             manifest['assignments']['agy-1']['bundle'], 'check pty crcrlf',
             '--evidence', str(manifest_path)],
            env=env, capture_output=True, text=True, check=False, timeout=60,
        )
        self.assertEqual(prompt_res.returncode, 0, prompt_res.stdout + prompt_res.stderr)
        prompt_path = session / 'r1-agy-1.prompt.md'
        pre_cmds, idx_cmds, post_cmds = self._build_seat_read_commands(session, manifest, 'agy-1')
        crlf_read = ["sed -n '1,5p' 'src/crlf_ref.py'"]
        all_cmds = pre_cmds + idx_cmds + post_cmds + crlf_read

        def inject_pty_crcrlf(_idx, cmd, formatted):
            # Replace wrapper and body CRLFs with \r\r\n and \r\r\r\n like macOS PTY capture.
            out = formatted.replace('code 0.\r\n\r\nCommand output:\r\n',
                                    'code 0.\r\r\n\r\r\nCommand output:\r\r\n', 1)
            lines = out.split('\r\n')
            if len(lines) > 6:
                lines[5] = lines[5] + '\r'
                lines[6] = lines[6] + '\r\r'
            if 'crlf_ref.py' in cmd and len(lines) > 7:
                # Mix \r\n and \r\r\n inside a CRLF source file.
                return '\r\n'.join(lines[:-1]) + '\r\r\n'
            return '\r\n'.join(lines)

        run = self._run_fake_agy_seat(
            'crcrlf', repo, session, prompt_path, 'agy-1',
            all_cmds, output_transform=inject_pty_crcrlf,
        )
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        audit = json.loads((session / 'r1-agy-1.read-audit.json').read_text(encoding='utf-8'))
        self.assertEqual(audit['status'], 'valid', audit)
        self.assertEqual(audit['violations'], [])
        self.assertEqual(audit['advisories'], [])

        # Negative checks: a lone mid-line \r or altered source byte must fail mismatch checks.
        rra = load('rra_crcrlf', LIB / 'review-read-audit.py')
        ev_file = self.root / 'crcrlf-events.jsonl'
        base_events = [json.loads(line) for line in ev_file.read_text(encoding='utf-8').splitlines()]

        bad_patch_events = json.loads(json.dumps(base_events))
        for ev in bad_patch_events:
            su = ev.get('step_update')
            if isinstance(su, dict) and su.get('state') == 'DONE' and su.get('step_index') == 1:
                head_sep = 'Command output:\r\r\n'
                header, body = su['tool_info']['output'].split(head_sep, 1)
                su['tool_info']['output'] = header + head_sep + body.replace('\n', '\rmidline\n', 1)
        bad_patch_stream = self.root / 'bad-patch.ndjson'
        bad_patch_stream.write_text(
            '\n'.join(json.dumps(e) for e in bad_patch_events) + '\n', encoding='utf-8',
        )
        res_patch, _ = rra.assessed(types.SimpleNamespace(
            adapter='agy', raw=str(bad_patch_stream), prompt=str(prompt_path),
            root=str(repo), session=str(session), deps=None, seat='agy-1',
            result=str(session / 'r1-agy-1.json'), out=str(self.root / 'bad-patch-audit.json'),
        ))
        self.assertIn('assigned-patch-output-mismatch',
                      {r['code'] for r in res_patch['violations']})

        bad_src_events = json.loads(json.dumps(base_events))
        for ev in bad_src_events:
            su = ev.get('step_update')
            if (isinstance(su, dict) and su.get('state') == 'DONE'
                    and 'crlf_ref.py' in (su.get('tool_info') or {}).get('parameters', {}).get('CommandLine', '')):
                su['tool_info']['output'] = su['tool_info']['output'].replace(
                    'crlf-updated', 'crlf-tamperd',
                )
        bad_src_stream = self.root / 'bad-src.ndjson'
        bad_src_stream.write_text(
            '\n'.join(json.dumps(e) for e in bad_src_events) + '\n', encoding='utf-8',
        )
        res_src, _ = rra.assessed(types.SimpleNamespace(
            adapter='agy', raw=str(bad_src_stream), prompt=str(prompt_path),
            root=str(repo), session=str(session), deps=None, seat='agy-1',
            result=str(session / 'r1-agy-1.json'), out=str(self.root / 'bad-src-audit.json'),
        ))
        self.assertIn('source-output-mismatch',
                      {r['code'] for r in res_src['violations'] + res_src['advisories']})

    def test_agy_multi_window_evidence_index_reads_credit_post_index_source_after_completion(self):
        agy_seats = [
            {'seat': f'agy-{i}', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False}
            for i in range(1, 4)
        ]
        _ev, repo, session, manifest_path, manifest, env = self._prepare_nav_overflow_fixture(
            'multi-idx', agy_seats,
        )
        ctx = manifest['source_context']['seats']['agy-1']
        self.assertTrue(ctx['source_read_required'])
        self.assertIsNotNone(
            manifest['task_capacity']['seats']['agy-1']['repository_source_target'],
        )
        prompt_res = subprocess.run(
            [str(SCRIPTS / 'rev-prompt.sh'), str(session), '1', 'agy-1',
             manifest['assignments']['agy-1']['bundle'], 'check multi-window index',
             '--evidence', str(manifest_path)],
            env=env, capture_output=True, text=True, check=False, timeout=60,
        )
        self.assertEqual(prompt_res.returncode, 0, prompt_res.stdout + prompt_res.stderr)
        prompt_path = session / 'r1-agy-1.prompt.md'
        result_file = session / 'r1-agy-1.json'
        result_file.write_text(
            json.dumps({'summary': 'No actionable issues found.', 'findings': []}),
            encoding='utf-8',
        )

        ev_path = session / 'r1-evidence.md'
        total_lines = len(ev_path.read_bytes().splitlines())
        self.assertGreaterEqual(total_lines, 30)
        q_ev = shlex.quote(str(ev_path))
        mid = total_lines // 3
        mid2 = (2 * total_lines) // 3
        pre_cmds, _cat_idx, post_cmds = self._build_seat_read_commands(session, manifest, 'agy-1')

        rra = load('rra_multi_idx', LIB / 'review-read-audit.py')

        def audit_cmds(tag, cmds, *, force_cat_truncated=False, inject_crcrlf_on=None,
                       corrupt_cmd=None):
            def transform(_idx, cmd, formatted):
                if force_cat_truncated and cmd.startswith('cat -- ') and 'evidence.md' in cmd:
                    return (
                        "The tool's output was truncated due to being too long.\n"
                        + formatted[:500]
                    )
                if inject_crcrlf_on and inject_crcrlf_on in cmd:
                    formatted = formatted.replace('\r\n', '\r\r\n')
                if corrupt_cmd and corrupt_cmd in cmd:
                    formatted = formatted[:-3] + 'X\r\n'
                return formatted

            return self._audit_fake_agy_stream(
                rra, tag, repo, session, prompt_path, 'agy-1', result_file,
                cmds, output_transform=transform,
            )

        # 1. Truncated cat followed by ordered sed -n windows + trailing past-EOF window + post-index source.
        slice1 = f"sed -n '1,{mid}p' {q_ev}"
        slice2 = f"sed -n '{mid + 1},{mid2}p' {q_ev}"
        slice3 = f"sed -n '{mid2 + 1},{total_lines + 40}p' {q_ev}"
        past_eof = f"sed -n '{total_lines + 41},{total_lines + 100}p' {q_ev}"
        doc1, codes1 = audit_cmds(
            'multi-ok',
            pre_cmds + [f'cat -- {q_ev}', slice1, slice2, slice3, past_eof] + post_cmds,
            force_cat_truncated=True,
            inject_crcrlf_on=f'{mid + 1},{mid2}p',
        )
        self.assertEqual(doc1['status'], 'valid', doc1)
        self.assertNotIn('missing-evidence-index', codes1)
        self.assertNotIn('missing-required-source-read', codes1)
        self.assertTrue(doc1['post_index_source_ranges'])

        # 2. Gap in slices fails both index and required post-index source.
        doc2, codes2 = audit_cmds('multi-gap', pre_cmds + [slice1, slice3] + post_cmds)
        self.assertEqual(doc2['status'], 'invalid')
        self.assertIn('missing-evidence-index', codes2)
        self.assertIn('missing-required-source-read', codes2)
        self.assertEqual(doc2['post_index_source_ranges'], [])

        # 3. Source read before completing all index windows earns no post-index credit.
        doc3, codes3 = audit_cmds(
            'multi-early',
            pre_cmds + [slice1] + post_cmds + [slice2, slice3],
        )
        self.assertEqual(doc3['status'], 'invalid')
        self.assertIn('missing-required-source-read', codes3)
        self.assertIn('evidence-read-order', codes3)
        self.assertEqual(doc3['post_index_source_ranges'], [])

        # 4. Compound, piped, and byte-altered index slices fail missing-evidence-index.
        for tag, bad_slices in (
            ('compound', [f"{slice1}; :", slice2, slice3]),
            ('piped', [f"{slice1} | head -20", slice2, slice3]),
        ):
            _doc, codes = audit_cmds('multi-' + tag, pre_cmds + bad_slices + post_cmds)
            self.assertIn('missing-evidence-index', codes)
        _doc_corr, codes_corr = audit_cmds(
            'multi-corrupt',
            pre_cmds + [slice1, slice2, slice3] + post_cmds,
            corrupt_cmd=f'{mid + 1},{mid2}p',
        )
        self.assertIn('missing-evidence-index', codes_corr)

        # 5. manifest is None prompt path with >10 KiB r1-evidence.md.
        no_man_sess = self.root / 'no-manifest-session'
        no_man_sess.mkdir()
        big_index = no_man_sess / 'r1-evidence.md'
        big_lines = [f'# line {i:03d} ' + ('k' * 90) for i in range(1, 131)]
        big_index.write_text('\n'.join(big_lines) + '\n', encoding='utf-8')
        self.assertGreater(len(big_index.read_bytes()), 10240)

        target_file = repo / 'src/lib.py'
        target_raw = target_file.read_bytes().splitlines(keepends=True)[:10]
        target_sha = hashlib.sha256(b''.join(target_raw)).hexdigest()
        head_tree = subprocess.run(
            ['git', '-C', str(repo), 'rev-parse', 'HEAD^{tree}'],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        blob_oid = subprocess.run(
            ['git', '-C', str(repo), 'hash-object', str(target_file)],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        no_man_prompt = no_man_sess / 'r1-agy-1.prompt.md'
        no_man_prompt.write_text(
            '## Scope\n'
            f'Evidence navigation index: {big_index}\n'
            f'Required post-index original-source target: src/lib.py:1-10 tree {head_tree} '
            f'blob {blob_oid} content SHA-256 {target_sha} reasons ["declaration:fn00"]\n',
            encoding='utf-8',
        )
        no_man_res = no_man_sess / 'r1-agy-1.json'
        no_man_res.write_text(
            json.dumps({'summary': 'No actionable issues found.', 'findings': []}),
            encoding='utf-8',
        )
        q_big = shlex.quote(str(big_index))

        def audit_no_man(tag, cmds, *, force_cat_truncated=False):
            def transform(_idx, cmd, formatted):
                if force_cat_truncated and cmd.startswith('cat -- '):
                    return (
                        "The tool's output was truncated due to being too long.\n"
                        + formatted[:500]
                    )
                return formatted

            doc, _ = self._audit_fake_agy_stream(
                rra, tag, repo, no_man_sess, no_man_prompt, 'agy-1', no_man_res,
                cmds, output_transform=transform,
            )
            return doc

        nm_ok = audit_no_man(
            'noman-ok',
            [
                f'cat -- {q_big}',
                f"sed -n '1,50p' {q_big}",
                f"sed -n '51,100p' {q_big}",
                f"sed -n '101,150p' {q_big}",
                "sed -n '1,10p' 'src/lib.py'",
            ],
            force_cat_truncated=True,
        )
        self.assertEqual(nm_ok['status'], 'valid', nm_ok)
        self.assertTrue(nm_ok['post_index_source_ranges'])

        nm_gap = audit_no_man(
            'noman-gap',
            [
                f"sed -n '1,50p' {q_big}",
                f"sed -n '101,150p' {q_big}",
                "sed -n '1,10p' 'src/lib.py'",
            ],
        )
        self.assertEqual(nm_gap['status'], 'invalid')
        self.assertIn('missing-evidence-index', {r['code'] for r in nm_gap['violations']})
        self.assertIn('missing-required-source-read', {r['code'] for r in nm_gap['violations']})

    def test_agy_prompts_cap_source_windows_at_100_lines(self):
        seats = [
            {'seat': 'agy-1', 'lab': 'google', 'adapter': 'agy',
             'model': 'gemini-4-hydrogen-xhigh', 'effort': 'xhigh', 'extra': False},
            {'seat': 'claude-1', 'lab': 'anthropic', 'adapter': 'claude',
             'model': 'sonnet', 'effort': 'max', 'extra': False},
        ]
        _ev, _repo, sess, mpath, man, env = self._prepare_nav_overflow_fixture('prompt-lines', seats)
        for seat in ('agy-1', 'claude-1'):
            res = subprocess.run(
                [str(SCRIPTS / 'rev-prompt.sh'), str(sess), '1', seat,
                 man['assignments'][seat]['bundle'], 'check prompt line limit',
                 '--evidence', str(mpath)],
                env=env, capture_output=True, text=True, check=False, timeout=60,
            )
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        agy_prompt = (sess / 'r1-agy-1.prompt.md').read_text(encoding='utf-8')
        claude_prompt = (sess / 'r1-claude-1.prompt.md').read_text(encoding='utf-8')
        self.assertIn('at most 100 lines', agy_prompt)
        self.assertIn('END - START + 1 <= 100', agy_prompt)
        self.assertNotIn('at most 240 lines', agy_prompt)
        self.assertIn('at most 240 lines', claude_prompt)


if __name__ == '__main__':
    unittest.main()
