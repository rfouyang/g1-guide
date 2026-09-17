from __future__ import annotations

import unittest

try:
    from util.g1_helper.g1_action_helper.g1_sport_mode_state_helper import (
        G1SportModeState,
    )
except ModuleNotFoundError as error:
    if error.name != "cyclonedds":
        raise
    G1SportModeState = None


class G1SportModeStateTests(unittest.TestCase):
    @unittest.skipIf(
        G1SportModeState is None,
        "CycloneDDS is available only with the hardware extra",
    )
    def test_matches_target_g1_hg_type_and_round_trips_cdr(self) -> None:
        assert G1SportModeState is not None
        state = G1SportModeState(501, 0, 4, 0.0)

        encoded_state = G1SportModeState.serialize(state)
        decoded_state = G1SportModeState.deserialize(encoded_state)

        self.assertEqual(
            G1SportModeState.__idl_typename__,
            "unitree_hg.msg.dds_.SportModeState_",
        )
        self.assertEqual(decoded_state, state)


if __name__ == "__main__":
    unittest.main()
