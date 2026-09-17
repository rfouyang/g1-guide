from __future__ import annotations

import unittest

from component.action.motion_lease import MotionLease, MotionOwner


class MotionLeaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lease = MotionLease()

    def test_one_owner_acquires_and_releases_lease(self) -> None:
        self.lease.acquire(MotionOwner.PRESENTATION)

        self.assertEqual(self.lease.owner, MotionOwner.PRESENTATION)

        self.lease.release(MotionOwner.PRESENTATION)
        self.assertEqual(self.lease.owner, MotionOwner.IDLE)

    def test_second_owner_is_rejected(self) -> None:
        self.lease.acquire(MotionOwner.NAVIGATION)

        with self.assertRaisesRegex(RuntimeError, "already owned by navigation"):
            self.lease.acquire(MotionOwner.PRESENTATION)

    def test_wrong_owner_cannot_release_lease(self) -> None:
        self.lease.acquire(MotionOwner.MAPPING)

        with self.assertRaisesRegex(RuntimeError, "mapping, not manual"):
            self.lease.release(MotionOwner.MANUAL)

    def test_idle_cannot_acquire_lease(self) -> None:
        with self.assertRaisesRegex(ValueError, "IDLE cannot acquire"):
            self.lease.acquire(MotionOwner.IDLE)


if __name__ == "__main__":
    unittest.main()
