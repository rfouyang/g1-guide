from __future__ import annotations

from dataclasses import dataclass

import cyclonedds.idl as idl
import cyclonedds.idl.annotations as annotate
from cyclonedds.idl.types import float32, uint32


@dataclass
@annotate.final
@annotate.autoid("sequential")
class G1SportModeState(
    idl.IdlStruct,
    typename="unitree_hg.msg.dds_.SportModeState_",
):
    """G1 sport-state IDL reconstructed from the target's DDS XTypes."""

    fsm_id: uint32
    fsm_mode: uint32
    task_id: uint32
    task_time: float32


def demo_g1_sport_mode_state_helper() -> None:
    state = G1SportModeState(501, 0, 4, 0.0)
    assert state.fsm_id == 501
    assert state.fsm_mode == 0
    print("G1 sport-mode state helper: offline IDL sample passed")


def main() -> None:
    demo_g1_sport_mode_state_helper()


if __name__ == "__main__":
    main()
