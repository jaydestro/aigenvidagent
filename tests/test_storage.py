import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from aigenvidagent.schema import BriefError
from aigenvidagent.storage import inside


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def test_existing_and_not_yet_created_paths(self):
        (self.root / "existing").mkdir()
        for relative in ("existing", "existing/new/file.json", "new/file.json"):
            with self.subTest(relative=relative):
                self.assertEqual(inside(self.root, relative), self.root / relative)

    def test_symlink_ancestor_is_rejected(self):
        target = self.root / "target"
        target.mkdir()
        link = self.root / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            if os.name != "nt" or error.winerror != 1314:
                raise
            self.skipTest("Creating symlinks requires Windows privileges")
        self.addCleanup(link.unlink)
        with self.assertRaisesRegex(BriefError, "Links/junctions"):
            inside(self.root, "link/new/file.json")

    @unittest.skipUnless(os.name == "nt", "Windows junctions only")
    def test_junction_ancestor_is_rejected(self):
        target = self.root / "target"
        target.mkdir()
        link = self.root / "junction"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
        self.addCleanup(link.rmdir)
        with self.assertRaisesRegex(BriefError, "Links/junctions"):
            inside(self.root, "junction/new/file.json")
