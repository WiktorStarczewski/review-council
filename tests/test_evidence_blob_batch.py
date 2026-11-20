"""Evidence validation reads Git blobs without starting one git process per blob."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from test_deleted_source_proof import load_evidence


class BlobBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='evidence-blobs-')
        base = Path(cls.temp.name).resolve()
        cls.root, cls.session = base / 'repo', base / 'session'
        cls.root.mkdir()
        cls.session.mkdir()
        config = base / 'gitconfig'
        config.write_text('[user]\n\tname = t\n\temail = t@t\n[commit]\n\tgpgsign = false\n')
        cls.env = dict(os.environ, GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1')
        cls.git('init', '-q')
        cls.bodies = {f'file{index:02d}.txt': f'line {index}\n'.encode() * (index + 1)
                      for index in range(30)}
        for name, body in cls.bodies.items():
            (cls.root / name).write_bytes(body)
        cls.git('add', '.')
        cls.git('commit', '-qm', 'base')
        cls.tree = cls.git('rev-parse', 'HEAD^{tree}')
        (cls.session / 'scope.env').write_text(
            f"REV_BASE={shlex.quote(cls.git('rev-parse', 'HEAD'))}\n"
            f'REV_ROOT={shlex.quote(str(cls.root))}\nREV_SCOPE=branch\n')
        cls.evidence = load_evidence()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @classmethod
    def git(cls, *args):
        return subprocess.run(['git', '-C', str(cls.root), *args], env=cls.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def started(self, call):
        """Run `call` and list the processes it starts; subprocess.run starts each by Popen."""
        commands = []
        real_popen = subprocess.Popen

        def popen(argv, *args, **kwargs):
            commands.append(argv)
            return real_popen(argv, *args, **kwargs)

        with patch.object(self.evidence.subprocess, 'Popen', popen):
            value = call()
        return value, commands

    def test_blob_reads_share_one_git_process(self):
        repository = self.evidence.Repository(self.session)
        entries = repository.entries(self.tree)
        bodies, commands = self.started(
            lambda: {name: repository.blob(entries[name]) for name in sorted(entries)})
        self.assertEqual(bodies, self.bodies)
        self.assertLessEqual(len(commands), 1,
                             f'{len(commands)} git processes read {len(entries)} blobs')

    def test_repeated_object_queries_start_one_git_process_each(self):
        names = sorted(self.bodies)[:10]
        entries = self.evidence.Repository(self.session).entries(self.tree)

        def queries():
            # The read audit's required-source lookups, once per assess pass, each pass with a
            # fresh repository view.
            answers = []
            for _ in range(3):
                repository = self.evidence.Repository(self.session)
                for name in names:
                    answers.append(repository.git('ls-tree', '-z', self.tree, '--', name))
                    answers.append(repository.git('cat-file', 'blob', entries[name][1]))
            return answers

        answers, commands = self.started(queries)
        expected = []
        for name in names:
            expected.append(subprocess.run(
                ['git', '-C', str(self.root), 'ls-tree', '-z', self.tree, '--', name],
                env=self.env, check=True, capture_output=True).stdout)
            expected.append(self.bodies[name])
        self.assertEqual(answers, expected * 3)
        lookups = [command for command in commands if 'rev-parse' not in command]
        self.assertLessEqual(len(lookups), len(names) + 1,
                             f'{len(lookups)} git processes answered {len(answers)} object queries')

    def test_a_missing_or_non_blob_object_fails_as_the_one_shot_read_does(self):
        repository = self.evidence.Repository(self.session)
        missing = ('100644', '0' * 40)
        with self.assertRaisesRegex(ValueError, '^git cat-file: '):
            repository.blob(missing)
        with self.assertRaisesRegex(ValueError, '^git cat-file: '):
            repository.blob(('100644', self.tree))
        self.assertEqual(repository.blob(('160000', self.tree)), b'')
        entries = repository.entries(self.tree)
        self.assertEqual(repository.blob(entries['file03.txt']), self.bodies['file03.txt'])


if __name__ == '__main__':
    unittest.main()
