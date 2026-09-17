from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from util.g1_helper.g1_action_helper.npz_helper import NpzHelper


class NpzHelperTests(unittest.TestCase):
    def test_reads_numeric_and_string_arrays_without_pickle(self) -> None:
        helper = NpzHelper()
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "action.npz"
            np.savez(
                archive_path,
                name=np.asarray("wave"),
                positions=np.zeros((2, 14)),
            )

            arrays = helper.read(archive_path)

        self.assertEqual(str(arrays["name"].item()), "wave")
        self.assertEqual(arrays["positions"].shape, (2, 14))

    def test_rejects_object_arrays(self) -> None:
        helper = NpzHelper()
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive_path = Path(temporary_directory) / "unsafe.npz"
            np.savez(archive_path, unsafe=np.asarray([{"command": 1}]))

            with self.assertRaisesRegex(ValueError, "Object arrays|object"):
                helper.read(archive_path)

    def test_rejects_non_npz_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "end in .npz"):
            NpzHelper().read(Path("action.npy"))


if __name__ == "__main__":
    unittest.main()
