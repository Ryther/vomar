"""A public build must exclude private evidence even if someone force-adds it."""
from pathlib import Path
import importlib.util
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
try:
    from tools.release import public_tree
except ImportError:
    public_tree=None


class PublicBoundary(unittest.TestCase):
    def test_private_paths_are_rejected_independently_of_gitignore(self):
        self.assertIsNotNone(public_tree,'Public export boundary has not been implemented')
        for path in ('inputs/vendor.bin','analysis/report.md','work/private/signing.jks',
                     '.codex/auth.json','.claude/settings.local.json','firmware/keys/signing-private.pem',
                     '../outside.txt','/absolute.txt','apps/x/build/output.apk','core.1234'):
            with self.subTest(path=path),self.assertRaises(ValueError):
                public_tree.validate_path(path)

    def test_synthetic_fixtures_public_keys_and_authored_sources_are_eligible(self):
        self.assertIsNotNone(public_tree,'Public export boundary has not been implemented')
        for path in ('firmware/src/main.c','firmware/keys/dev-public.pem',
                     'apps/android-updater/test-fixtures/synthetic-common.zip',
                     'apps/android-updater/gradle/wrapper/gradle-wrapper.jar',
                     'integrations/zigbee2mqtt/dist/vimar_30805.js'):
            public_tree.validate_path(path)

    def test_new_unreviewed_file_is_ignored_by_default(self):
        result=subprocess.run(['git','check-ignore','--no-index','--quiet','unreviewed-sensitive-file.conf'],cwd=ROOT)
        self.assertEqual(result.returncode,0,'Public source policy must deny unreviewed new paths')


if __name__=='__main__':
    unittest.main()
