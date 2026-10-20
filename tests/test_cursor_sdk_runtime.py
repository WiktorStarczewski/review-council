"""Synthetic verifier and launcher controls cannot issue live qualification."""

import base64
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile

from test_cursor_sdk import CursorSDKCase, DRIVER, FIXTURES, SCRIPTS


RUNTIME_SCRIPTS = SCRIPTS / 'cursor-sdk'
VERIFIER = RUNTIME_SCRIPTS / 'verify-runtime.py'
LAUNCHER = RUNTIME_SCRIPTS / 'launch.mjs'


class RuntimeFixture:
    def __init__(self, directory):
        self.directory = directory
        self.controller = directory / 'controller'
        self.scripts = self.controller / 'plugins/review-council/scripts'
        shutil.copytree(SCRIPTS, self.scripts)
        for copied in (self.scripts, *self.scripts.rglob('*')):
            if not copied.is_symlink():
                copied.chmod(copied.stat().st_mode | 0o700)
        self.templates = self.scripts / 'cursor-sdk'
        self.runtime = directory / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.archives = self.runtime / '.archives'
        self.archives.mkdir(mode=0o700)
        self.platform = {'Darwin': 'darwin', 'Linux': 'linux'}[platform.system()]
        self.arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'x64',
                     'AMD64': 'x64'}[platform.machine()]
        self.helper = f'@cursor/sdk-{self.platform}-{self.arch}'
        self.sdk_files = {'package.json': self.json_bytes({
            'name': '@cursor/sdk', 'version': '1.0.38', 'type': 'module'}),
            'dist/esm/index.js': b'export const synthetic = true;\n'}
        self.helper_files = {'package.json': self.json_bytes({
            'name': self.helper, 'version': '1.0.38',
            'os': [self.platform], 'cpu': [self.arch]}),
            'bin/rg': b'synthetic helper bytes, never executed\n'}
        self.lock = {'name': 'synthetic-council-runtime', 'version': '1.0.0',
                     'lockfileVersion': 3, 'requires': True, 'packages': {
                         '': {'name': 'synthetic-council-runtime', 'version': '1.0.0',
                              'dependencies': {'@cursor/sdk': '1.0.38'}}}}
        self.write_package('@cursor/sdk', self.sdk_files)
        self.write_package(self.helper, self.helper_files, native=True)
        self.package = {'name': 'synthetic-council-runtime', 'version': '1.0.0',
                        'private': True, 'type': 'module',
                        'dependencies': {'@cursor/sdk': '1.0.38'}}
        for name in ('package.json', 'package-lock.json'):
            self.write_template(name, self.package if name == 'package.json' else self.lock)
        shutil.copyfile(LAUNCHER, self.runtime / 'launch.mjs')
        self.verifier = self.templates / 'verify-runtime.py'

    @staticmethod
    def json_bytes(value):
        return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()

    def write_template(self, name, value):
        content = self.json_bytes(value)
        (self.templates / name).write_bytes(content)
        (self.runtime / name).write_bytes(content)

    def archive_bytes(self, files, extra=()):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w:gz', format=tarfile.USTAR_FORMAT) as archive:
            for name, content in files.items():
                member = tarfile.TarInfo('package/' + name)
                member.size = len(content)
                member.mode = 0o755 if name.startswith('bin/') else 0o644
                archive.addfile(member, io.BytesIO(content))
            for member, content in extra:
                archive.addfile(member, io.BytesIO(content) if content is not None else None)
        return output.getvalue()

    def write_package(self, name, files, native=False, extra=()):
        content = self.archive_bytes(files, extra)
        integrity = 'sha512-' + base64.b64encode(hashlib.sha512(content).digest()).decode()
        archive = self.archives / (hashlib.sha256(integrity.encode()).hexdigest() + '.tgz')
        archive.write_bytes(content)
        target = self.runtime / 'node_modules' / name
        target.mkdir(parents=True, mode=0o700, exist_ok=True)
        for relative, data in files.items():
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o755 if relative.startswith('bin/') else 0o644)
        entry = {'version': '1.0.38', 'resolved': 'https://registry.invalid/synthetic.tgz',
                 'integrity': integrity}
        if native:
            entry.update(optional=True, os=[self.platform], cpu=[self.arch])
        else:
            entry['optionalDependencies'] = {self.helper: '1.0.38'}
        self.lock['packages']['node_modules/' + name] = entry
        return archive

    def replace_sdk_archive(self, extra):
        self.write_package('@cursor/sdk', self.sdk_files, extra=extra)
        self.write_template('package-lock.json', self.lock)

    def archive_path(self, name='@cursor/sdk'):
        integrity = self.lock['packages']['node_modules/' + name]['integrity']
        return self.archives / (hashlib.sha256(integrity.encode()).hexdigest() + '.tgz')

    def files(self):
        return {str(path.relative_to(self.directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.directory.rglob('*') if path.is_file() and not path.is_symlink()}


class CursorRuntimeIntegrityTests(CursorSDKCase):
    def fixture(self):
        self.require_entry(VERIFIER)
        self.require_entry(LAUNCHER)
        return RuntimeFixture(self.directory)

    def verify(self, fixture, wrapper=None, *arguments):
        command = [sys.executable, str(fixture.verifier), str(fixture.runtime)]
        if wrapper:
            command = [sys.executable, str(wrapper), str(fixture.verifier),
                       str(fixture.runtime), *map(str, arguments)]
        return subprocess.run(command, env=dict(self.env, PYTHONDONTWRITEBYTECODE='1'),
                              capture_output=True, text=True, timeout=25)

    def valid(self, fixture):
        process = self.verify(fixture)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, '')
        self.assertLess(len(process.stdout.encode()), 2048)
        result = json.loads(process.stdout)
        self.assertEqual(set(result), {'version', 'sdk_version', 'runtime_sha256',
                                       'platform', 'arch', 'helper'})
        self.assertEqual(result['version'], 1)
        self.assertEqual(result['sdk_version'], '1.0.38')
        self.assertEqual(result['platform'], fixture.platform)
        self.assertEqual(result['arch'], fixture.arch)
        self.assertEqual(result['helper'], fixture.helper)
        self.assertRegex(result['runtime_sha256'], r'\A[0-9a-f]{64}\Z')
        return result

    def refused(self, fixture, wrapper=None, *arguments):
        process = self.verify(fixture, wrapper, *arguments)
        self.assertEqual((process.returncode, process.stdout, process.stderr),
                         (5, '', 'runtime_invalid\n'))

    def test_authenticated_synthetic_packages_have_a_stable_digest_without_extraction(self):
        fixture = self.fixture()
        before = fixture.files()
        first = self.valid(fixture)
        self.assertEqual(self.valid(fixture), first)
        self.assertEqual(fixture.files(), before, 'verification must not extract, install or write')
        self.assertFalse((self.directory / 'qualification.json').exists())

    def test_verifier_accepts_exactly_one_explicit_runtime_argument(self):
        fixture = self.fixture()
        self.valid(fixture)
        for arguments in ([], [str(fixture.runtime), 'unexpected-extra-argument']):
            with self.subTest(arguments=arguments):
                process = subprocess.run([sys.executable, str(fixture.verifier), *arguments],
                                         env=self.env, capture_output=True, text=True, timeout=25)
                self.assertEqual((process.returncode, process.stdout, process.stderr),
                                 (5, '', 'runtime_invalid\n'))

    def test_changed_archive_bytes_fail_the_committed_integrity(self):
        fixture = self.fixture()
        self.valid(fixture)
        original_lock = json.loads(json.dumps(fixture.lock))
        original_archive = fixture.archive_path()
        alternate_files = dict(fixture.sdk_files)
        alternate_files['dist/esm/index.js'] = b'export const synthetic = false;\n'
        alternate_archive = fixture.write_package('@cursor/sdk', alternate_files)
        fixture.write_template('package-lock.json', fixture.lock)
        self.valid(fixture)
        alternate_bytes = alternate_archive.read_bytes()
        fixture.lock = original_lock
        fixture.write_template('package-lock.json', original_lock)
        original_archive.write_bytes(alternate_bytes)
        self.refused(fixture)

    def test_changed_installed_bytes_cannot_be_replaced_by_archive_metadata(self):
        fixture = self.fixture()
        self.valid(fixture)
        (fixture.runtime / 'node_modules/@cursor/sdk/dist/esm/index.js').write_bytes(b'changed\n')
        self.refused(fixture)

    def test_extra_installed_files_are_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        (fixture.runtime / 'node_modules/@cursor/sdk/extra.js').write_text('extra\n')
        self.refused(fixture)

    def test_missing_installed_package_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        shutil.rmtree(fixture.runtime / 'node_modules/@cursor/sdk')
        self.refused(fixture)

    def test_missing_applicable_archive_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        fixture.archive_path().unlink()
        self.refused(fixture)

    def test_missing_native_helper_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        shutil.rmtree(fixture.runtime / 'node_modules' / fixture.helper)
        self.refused(fixture)

    def test_wrong_native_helper_does_not_substitute_for_the_host_package(self):
        fixture = self.fixture()
        self.valid(fixture)
        actual = fixture.runtime / 'node_modules' / fixture.helper
        actual.rename(actual.with_name('sdk-wrong-platform'))
        self.refused(fixture)

    def test_inapplicable_native_package_cannot_satisfy_platform_selection(self):
        fixture = self.fixture()
        self.valid(fixture)
        entry = fixture.lock['packages']['node_modules/' + fixture.helper]
        entry['os'] = ['win32']
        fixture.write_template('package-lock.json', fixture.lock)
        self.refused(fixture)

    def test_inapplicable_native_architecture_cannot_satisfy_helper_selection(self):
        fixture = self.fixture()
        self.valid(fixture)
        entry = fixture.lock['packages']['node_modules/' + fixture.helper]
        entry['cpu'] = ['inapplicable-architecture']
        fixture.write_template('package-lock.json', fixture.lock)
        self.refused(fixture)

    def test_nonprivate_runtime_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        fixture.runtime.chmod(0o755)
        self.refused(fixture)

    def test_runtime_owned_by_a_different_effective_user_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        marker = self.directory / 'synthetic-principal-changed'
        target = fixture.runtime / 'package.json'
        self.refused(fixture, FIXTURES / 'cursor-sdk-runtime-race.py', 'owner',
                     target, target, target, marker)
        self.assertEqual(marker.read_text(), 'synthetic principal changed\n')

    def test_symlink_runtime_root_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        actual = fixture.runtime.with_name('real-runtime')
        fixture.runtime.rename(actual)
        fixture.runtime.symlink_to(actual, target_is_directory=True)
        self.refused(fixture)

    def test_symlink_parent_component_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        alias = self.directory / 'redirected-parent'
        alias.symlink_to(self.directory, target_is_directory=True)
        fixture.runtime = alias / 'runtime'
        self.refused(fixture)

    def test_symlink_installed_package_component_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        package = fixture.runtime / 'node_modules/@cursor/sdk'
        target = self.directory / 'redirected-package'
        package.rename(target)
        package.symlink_to(target, target_is_directory=True)
        self.refused(fixture)

    def test_symlink_archive_file_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        archive = fixture.archive_path()
        target = self.directory / 'redirected-archive.tgz'
        archive.rename(target)
        archive.symlink_to(target)
        self.refused(fixture)

    def test_symlink_installed_file_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        path = fixture.runtime / 'node_modules/@cursor/sdk/dist/esm/index.js'
        target = self.directory / 'redirected-source.js'
        path.rename(target)
        path.symlink_to(target)
        self.refused(fixture)

    def test_symlink_runtime_template_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        path = fixture.runtime / 'package-lock.json'
        target = self.directory / 'redirected-lock.json'
        path.rename(target)
        path.symlink_to(target)
        self.refused(fixture)

    def test_multiply_linked_archive_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        os.link(fixture.archive_path(), self.directory / 'second-archive-link.tgz')
        self.refused(fixture)

    def test_multiply_linked_installed_file_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        path = fixture.runtime / 'node_modules/@cursor/sdk/dist/esm/index.js'
        os.link(path, self.directory / 'second-source-link.js')
        self.refused(fixture)

    def test_nonregular_installed_file_is_refused_without_blocking(self):
        fixture = self.fixture()
        self.valid(fixture)
        path = fixture.runtime / 'node_modules/@cursor/sdk/dist/esm/index.js'
        path.unlink()
        os.mkfifo(path)
        self.refused(fixture)

    def archive_member_refused(self, name, kind=tarfile.REGTYPE, linkname=''):
        fixture = self.fixture()
        self.valid(fixture)
        member = tarfile.TarInfo(name)
        member.type = kind
        member.linkname = linkname
        member.size = 0
        fixture.replace_sdk_archive([(member, b'' if kind == tarfile.REGTYPE else None)])
        before = fixture.files()
        self.refused(fixture)
        self.assertEqual(fixture.files(), before, 'untrusted tar entries must never be extracted')

    def test_archive_traversal_is_refused_without_extraction(self):
        self.archive_member_refused('package/../../escaped')
        self.assertFalse((self.directory / 'escaped').exists())

    def test_absolute_archive_member_is_refused_without_extraction(self):
        self.archive_member_refused(str(self.directory / 'absolute-escape'))
        self.assertFalse((self.directory / 'absolute-escape').exists())

    def test_nonpackage_archive_member_is_refused(self):
        self.archive_member_refused('outside/file.js')

    def test_duplicate_archive_members_are_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        original = fixture.sdk_files['dist/esm/index.js']
        duplicate = tarfile.TarInfo('package/dist/esm/index.js')
        duplicate.size = len(original)
        duplicate.mode = 0o644
        fixture.replace_sdk_archive([(duplicate, original)])
        before = fixture.files()
        self.refused(fixture)
        self.assertEqual(fixture.files(), before, 'duplicate members must never be extracted')

    def test_archive_symbolic_link_is_refused(self):
        self.archive_member_refused('package/link', tarfile.SYMTYPE, '../../outside')

    def test_archive_hard_link_is_refused(self):
        self.archive_member_refused('package/link', tarfile.LNKTYPE, 'package/dist/esm/index.js')

    def test_archive_device_member_is_refused(self):
        self.archive_member_refused('package/device', tarfile.CHRTYPE)

    def test_excessive_archive_member_count_is_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        files = dict(fixture.sdk_files)
        files.update({f'empty/{index:05d}': b'' for index in range(9999)})
        fixture.write_package('@cursor/sdk', files)
        fixture.write_template('package-lock.json', fixture.lock)
        self.assertEqual(len(files), 10001)
        self.refused(fixture)

    def test_excessive_declared_archive_bytes_are_refused(self):
        fixture = self.fixture()
        self.valid(fixture)
        size = 256 * 1024 * 1024 + 1

        class ZeroReader:
            def read(self, count):
                return b'\0' * count

        archive_path = self.directory / 'bounded-size.tgz'
        with tarfile.open(archive_path, mode='w:gz', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in fixture.sdk_files.items():
                member = tarfile.TarInfo('package/' + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            member = tarfile.TarInfo('package/oversized.bin')
            member.size = size
            archive.addfile(member, ZeroReader())
        content = archive_path.read_bytes()
        integrity = 'sha512-' + base64.b64encode(hashlib.sha512(content).digest()).decode()
        fixture.lock['packages']['node_modules/@cursor/sdk']['integrity'] = integrity
        retained = fixture.archives / (hashlib.sha256(integrity.encode()).hexdigest() + '.tgz')
        archive_path.rename(retained)
        installed = fixture.runtime / 'node_modules/@cursor/sdk/oversized.bin'
        with installed.open('wb') as stream:
            stream.truncate(size)
        fixture.write_template('package-lock.json', fixture.lock)
        self.refused(fixture)

    def test_native_helper_executable_mode_is_bound_to_the_archive(self):
        fixture = self.fixture()
        self.valid(fixture)
        (fixture.runtime / 'node_modules' / fixture.helper / 'bin/rg').chmod(0o644)
        self.refused(fixture)

    def test_nonhelper_package_executable_modes_are_bound_to_the_archive(self):
        fixture = self.fixture()
        self.valid(fixture)
        (fixture.runtime / 'node_modules/@cursor/sdk/dist/esm/index.js').chmod(0o755)
        self.refused(fixture)

    def test_runtime_templates_must_equal_the_controller_bytes(self):
        fixture = self.fixture()
        self.valid(fixture)
        for name in ('package.json', 'package-lock.json', 'launch.mjs'):
            with self.subTest(template=name):
                path = fixture.runtime / name
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                self.refused(fixture)
                path.write_bytes(original)
        self.valid(fixture)

    def test_controller_source_changes_alter_the_runtime_digest(self):
        fixture = self.fixture()
        first = self.valid(fixture)
        inputs = (
            'cursor-sdk/verify-runtime.py', 'cursor-sdk/launch.mjs',
            'cursor-sdk/package.json', 'cursor-sdk/package-lock.json',
            'lib/cursor-sdk-driver.mjs', 'lib/cursor-sdk-reader.mjs',
            'lib/cursor-read-helper.py', 'lib/review-read-audit.py',
            'seats.d/cursor-sdk.sh',
        )
        runtime_templates = {'launch.mjs', 'package.json', 'package-lock.json'}
        for name in inputs:
            with self.subTest(controller_input=name):
                source = fixture.scripts / name
                self.assertTrue(source.is_file(), 'runtime digest must bind ' + name)
                originals = {source: source.read_bytes()}
                if name.startswith('cursor-sdk/') and source.name in runtime_templates:
                    installed = fixture.runtime / source.name
                    originals[installed] = installed.read_bytes()
                try:
                    for path, original in originals.items():
                        path.write_bytes(original + b'\n')
                    changed = self.valid(fixture)
                    self.assertNotEqual(changed['runtime_sha256'], first['runtime_sha256'],
                                        'runtime digest omitted controller input: ' + name)
                finally:
                    for path, original in originals.items():
                        path.write_bytes(original)
                self.assertEqual(self.valid(fixture), first,
                                 'restoring ' + name + ' must restore the stable baseline')

    def test_authenticated_archive_bytes_cannot_be_swapped_before_member_parsing(self):
        fixture = self.fixture()
        self.valid(fixture)
        replacement_files = dict(fixture.sdk_files)
        replacement_files['dist/esm/index.js'] = b'unauthenticated replacement\n'
        replacement = self.directory / 'replacement.tgz'
        replacement.write_bytes(fixture.archive_bytes(replacement_files))
        marker = self.directory / 'archive-swapped'
        self.refused(fixture, FIXTURES / 'cursor-sdk-runtime-race.py', 'archive',
                     fixture.archive_path(), replacement,
                     fixture.runtime / 'node_modules/@cursor/sdk/dist/esm/index.js', marker)
        self.assertEqual(marker.read_text(), 'swapped\n', 'the deterministic race must actually occur')

    def test_installed_path_replacement_cannot_validate_a_different_inode(self):
        fixture = self.fixture()
        self.valid(fixture)
        target = fixture.runtime / 'node_modules/@cursor/sdk/dist/esm/index.js'
        replacement = self.directory / 'replacement.js'
        replacement.write_bytes(b'unauthenticated installed bytes\n')
        marker = self.directory / 'installed-swapped'
        self.refused(fixture, FIXTURES / 'cursor-sdk-runtime-race.py', 'installed',
                     target, replacement, target, marker)
        self.assertEqual(marker.read_text(), 'swapped\n', 'descriptor replacement must be exercised')


class CursorInstalledLauncherTests(CursorSDKCase):
    def fixture(self):
        self.require_entry(LAUNCHER)
        runtime = self.directory / 'runtime'
        runtime.mkdir(mode=0o700)
        launch = runtime / 'launch.mjs'
        shutil.copyfile(LAUNCHER, launch)
        driver = self.directory / 'inert-controller-driver.mjs'
        shutil.copyfile(FIXTURES / 'cursor-sdk-launcher-inert.mjs', driver)
        record = self.directory / 'launcher-record.json'
        return launch, driver, record

    def test_installed_entry_preserves_exact_argv_and_invokes_the_driver_once(self):
        launch, driver, record = self.fixture()
        shell_marker = self.directory / 'must-not-exist'
        arguments = ['seat', 'with spaces', '', 'β', '--root',
                     '$(touch ' + str(shell_marker) + ')', '`touch ' + str(shell_marker) + '`', '*']
        environment = dict(self.env, SYNTHETIC_LAUNCH_RECORD=str(record),
                           SYNTHETIC_LAUNCH_NONCE='synthetic-launch-nonce')
        process = self.node(launch, driver, *arguments, environment=environment)
        self.assertEqual((process.returncode, process.stdout, process.stderr), (0, '', ''))
        observed = json.loads(record.read_text())
        self.assertEqual(observed, {'synthetic': True, 'calls': 1,
                                   'entry': str(launch), 'argv': arguments,
                                   'nonce': 'synthetic-launch-nonce'})
        self.assertFalse(shell_marker.exists(), 'arguments must never pass through a shell')
        self.assertEqual(launch.read_bytes(), LAUNCHER.read_bytes())

    def test_installed_entry_preserves_the_driver_exit_classification(self):
        launch, driver, record = self.fixture()
        environment = dict(self.env, SYNTHETIC_LAUNCH_RECORD=str(record),
                           SYNTHETIC_LAUNCH_NONCE='synthetic-launch-nonce')
        control = self.node(launch, driver, 'seat', environment=environment)
        self.assertEqual((control.returncode, control.stdout, control.stderr), (0, '', ''))
        self.assertEqual(json.loads(record.read_text())['calls'], 1)
        record.unlink()
        refused = self.node(launch, driver, 'closed-quota-fixture', environment=environment)
        self.assertEqual((refused.returncode, refused.stdout, refused.stderr), (4, '', ''))
        self.assertEqual(json.loads(record.read_text())['argv'], ['closed-quota-fixture'])
        self.assertEqual(json.loads(record.read_text())['calls'], 1)

    def test_installed_entry_closes_import_and_driver_failures_without_private_errors(self):
        launch, driver, record = self.fixture()
        original = driver.read_bytes()
        environment = dict(self.env, SYNTHETIC_LAUNCH_RECORD=str(record),
                           SYNTHETIC_LAUNCH_NONCE='synthetic-launch-nonce')
        for source in ('throw new Error("private-import-canary");\n',
                       'export async function runDriver() { throw new Error("private-driver-canary"); }\n',
                       'export const unrelated = true;\n'):
            with self.subTest(source=source):
                driver.write_bytes(original)
                control = self.node(launch, driver, 'seat', environment=environment)
                self.assertEqual((control.returncode, control.stdout, control.stderr), (0, '', ''))
                self.assertEqual(json.loads(record.read_text())['calls'], 1)
                record.unlink()
                driver.write_text(source)
                process = self.node(launch, driver, 'seat', environment=environment)
                self.assertEqual(process.returncode, 1)
                self.assertEqual(process.stdout, '')
                self.assertRegex(process.stderr, r'\A[a-z][a-z0-9_]{0,63}\n\Z')
                self.assertNotIn('private-', process.stderr)
                self.assertFalse(record.exists())


class CursorAcquisitionAbortTests(CursorSDKCase):
    def exercise(self, stage, late=False):
        self.require_entry(DRIVER)
        fixture = FIXTURES / 'cursor-sdk-acquisition-double.mjs'
        self.require_entry(fixture)
        workspace = self.directory / 'workspace'
        workspace.mkdir(mode=0o700)
        selection = {'id': 'grok-9.10', 'params': [{'id': 'reasoning', 'value': 'xhigh'}],
                     'maxMode': True}
        spec = {'selection': selection, 'prompt': 'Frozen acquisition fixture.\n',
                'terminal': {'id': 'synthetic-run', 'status': 'finished', 'model': selection,
                             'result': '{"summary":"Synthetic acquisition control","findings":[]}'}}
        path = self.directory / 'spec.json'
        path.write_text(json.dumps(spec))
        process = self.node(fixture, DRIVER, path, workspace, stage, 'late' if late else 'never')
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stderr, '')
        self.assertNotIn('synthetic-acquisition-key', process.stdout)
        result = json.loads(process.stdout)
        self.assertTrue(result['synthetic'])
        control = result['control']
        self.assertEqual(control['outcome']['exitCode'], 0)
        self.assertEqual(control['outcome']['reason'], 'transport_finished')
        for name in ('Agent.create', 'agent:send', 'run:stream', 'run:wait',
                     'reader:dispose', 'agent:close'):
            self.assertEqual(control['trace'].count(name), 1)
        self.assertEqual(control['trace'].count('run:cancel'), 0)
        observed = result['observed']
        self.assertNotEqual(observed['outcome']['exitCode'], 0)
        self.assertRegex(observed['outcome']['reason'], r'\A[a-z][a-z0-9_]{0,63}\Z')
        self.assertEqual(observed['trace'].count('Agent.create'), 1)
        self.assertEqual(observed['trace'].count('reader:dispose'), 1)
        self.assertEqual(observed['trace'].count('run:stream'), 0)
        self.assertEqual(observed['trace'].count('run:wait'), 0)
        self.assertEqual(observed['raw'], [])
        self.assertEqual(observed['lateEvents'], 0)
        self.assertEqual(list(workspace.iterdir()), [])
        return observed

    def test_abort_during_unresolved_agent_create_settles_without_a_turn(self):
        observed = self.exercise('create')
        self.assertEqual(observed['trace'].count('agent:send'), 0)
        self.assertEqual(observed['trace'].count('agent:close'), 0)
        self.assertEqual(observed['trace'].count('run:cancel'), 0)

    def test_abort_during_unresolved_send_settles_and_closes_the_agent_once(self):
        observed = self.exercise('send')
        self.assertEqual(observed['trace'].count('agent:send'), 1)
        self.assertEqual(observed['trace'].count('agent:close'), 1)
        self.assertEqual(observed['trace'].count('run:cancel'), 0)

    def test_agent_acquired_after_abort_is_closed_once_without_sending(self):
        observed = self.exercise('create', late=True)
        self.assertEqual(observed['beforeLate'].count('agent:close'), 0)
        self.assertEqual(observed['trace'].count('agent:close'), 1)
        self.assertEqual(observed['trace'].count('agent:send'), 0)
        self.assertEqual(observed['trace'].count('run:cancel'), 0)

    def test_run_acquired_after_abort_is_cancelled_once_without_streaming(self):
        observed = self.exercise('send', late=True)
        self.assertEqual(observed['beforeLate'].count('run:cancel'), 0)
        self.assertEqual(observed['trace'].count('agent:send'), 1)
        self.assertEqual(observed['trace'].count('agent:close'), 1)
        self.assertEqual(observed['trace'].count('run:cancel'), 1)
