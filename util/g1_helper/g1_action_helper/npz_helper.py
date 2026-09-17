from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import numpy as np
from numpy.typing import NDArray


class NpzHelper:
    """Read bounded NumPy archives without enabling pickle."""

    MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
    MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024

    def read(self, archive_path: Path) -> dict[str, NDArray[np.generic]]:
        if archive_path.suffix.lower() != ".npz":
            raise ValueError(f"Action archive must end in .npz: {archive_path}")
        if not archive_path.is_file():
            raise FileNotFoundError(f"Action archive does not exist: {archive_path}")
        if archive_path.stat().st_size > self.MAX_ARCHIVE_BYTES:
            raise ValueError("Action archive exceeds the compressed size limit")

        self._validate_zip(archive_path)
        try:
            loaded = np.load(archive_path, allow_pickle=False)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            raise ValueError(f"Could not read action archive: {error}") from error
        if not isinstance(loaded, np.lib.npyio.NpzFile):
            raise ValueError("Action file must be an NPZ archive")

        try:
            with loaded as archive:
                arrays = {
                    name: self._copy_array(name, archive[name])
                    for name in archive.files
                }
        except ValueError as error:
            raise ValueError(f"Could not read action archive arrays: {error}") from error
        if not arrays:
            raise ValueError("Action archive cannot be empty")
        return arrays

    def _validate_zip(self, archive_path: Path) -> None:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                entries = archive.infolist()
        except zipfile.BadZipFile as error:
            raise ValueError("Action file is not a valid NPZ archive") from error

        if not entries:
            raise ValueError("Action archive cannot be empty")
        uncompressed_bytes = 0
        for entry in entries:
            entry_path = Path(entry.filename)
            if (
                entry.is_dir()
                or entry_path.name != entry.filename
                or entry_path.suffix != ".npy"
            ):
                raise ValueError(f"Invalid NPZ entry: {entry.filename}")
            uncompressed_bytes += entry.file_size
        if uncompressed_bytes > self.MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Action archive exceeds the uncompressed size limit")

    def _copy_array(
        self,
        name: str,
        array: NDArray[np.generic],
    ) -> NDArray[np.generic]:
        if not name or "/" in name or "\\" in name:
            raise ValueError(f"Invalid array name: {name!r}")
        if array.dtype.hasobject:
            raise ValueError(f"Array {name} cannot use object dtype")
        copied_array = array.copy()
        return copied_array


def demo_npz_helper() -> None:
    helper = NpzHelper()
    with tempfile.TemporaryDirectory() as temporary_directory:
        archive_path = Path(temporary_directory) / "action.npz"
        np.savez(
            archive_path,
            timestamps=np.asarray([0.0, 0.04]),
            joint_positions=np.zeros((2, 14)),
        )
        arrays = helper.read(archive_path)
    assert arrays["joint_positions"].shape == (2, 14)
    print("NPZ helper: safe array loading verified")


def main() -> None:
    demo_npz_helper()


if __name__ == "__main__":
    main()
