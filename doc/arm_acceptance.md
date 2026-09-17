# Two-arm commissioning checklist

Reviewed: 2026-09-17T10:37:50Z

## First attempt and follow-up

The authorized 2026-09-17T10:15:40Z run aborted during start transition when the
guard rejected mode state. Before/after snapshots show FSM 501/0 then 501/1,
mode_pr 0; release publication completed. Operator subsequently confirmed normal
standing and arms. No automatic retry was made and acceptance remains pending.

The restriction to mode 0 is our conservative commissioning policy, **not** an
assertion from the upstream arm7 example. The official
[built-in arm-action client](https://github.com/unitreerobotics/unitree_ros2/blob/master/example/src/include/g1/g1_arm_action_client.hpp)
permits FSM 501 but does not define mode 1 or prove its meaning for custom
arm-SDK takeover on firmware 1.5.4. The current official
[G1 locomotion API](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/g1/loco/g1_loco_api.hpp)
names internal-control selector values 0, 1 and 2 as `LAST`, `PASSIVE` and
`WALKRUN`. Its
[client implementation](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/g1/loco/g1_loco_client.hpp)
sends those values to `SwitchToInternalCtrl`, while `GetFsmMode` exposes an
integer without documenting its interpretation within FSM 501. This makes mode
1 safety-sensitive evidence, but does not prove that the observed 501/1 tuple
was caused by arm-SDK takeover or has the same semantics as the selector.
Do not infer mode semantics merely from temporal correlation with this run.

Future attempts persist `_rejected.json` for the actual guard rejection and
`_execution.json` for completion/error and successful publication counts, in
addition to before/after generic snapshots. Publication success is not physical
acknowledgement. The original attempt's command count remains unknown. All 73
offline tests passed after this instrumentation; the guard is unchanged.

## Implemented single-run entry point

`app.arm_commissioning` now provides a separate commissioning path without
changing `hardware_verified`. Default invocation is offline:

```bash
uv run python -m app.arm_commissioning
```

Implementation follows the vendored
`example/g1/high_level/g1_arm7_sdk_dds_example.py`: `rt/arm_sdk`, CRC, authority
slot 29, and a gradual normal-exit authority fade. Unlike that example, it does
not include waist joints or request a zero full-body posture. Only indices
15–28 receive arm control gains. It never constructs a locomotion command
client. The existing optional base-stop callback is not supplied on this path.

The commissioning service restricts action selection to `present_left`, requires
explicit live confirmation and a live state guard, stretches playback from 4 s
to 16 s, returns to this run's measured initial arm positions over at least 8 s,
then fades authority over 3 s. The initial transition remains 2 s and is checked
against velocity/acceleration limits. The guard restricts the observed target to
firmware 1.5.4, FSM 501/0 and mode_pr 0 and rechecks subscriber preflight evidence
throughout execution. Ctrl-C/SIGTERM requests cancellation; cancellation/fault
does not attempt the normal return trajectory and instead attempts immediate
zero-authority release. This is not a verified physical emergency stop.

After the on-site operator confirms stable standing, sufficient battery, no
active competing arm controller, clearance for both arms, and emergency-stop
coverage, the explicit entry point is:

```bash
CYCLONEDDS_HOME="$PWD/third_party/cyclonedds/install" uv run --extra hardware \
  python -m app.arm_commissioning --live --interface eth0 \
  --confirm-arm-motion --confirm-clear-workspace --confirm-standing \
  --observed-model-id unitree_g1_29dof_rev_1_0_fake_hand \
  --observed-firmware-version 1.5.4
```

This command was run once at 2026-09-17T10:15:40Z and aborted when the continuous
guard observed FSM 501/1. It must not be retried until that state is understood.
The current 73-test offline suite passes, including commissioning on an
unverified contract, slow single-run return/fade, guard changes, blocked cleanup,
failure evidence and no-DDS default mode. Before/after subscriber reports are
saved under ignored `output/arm_commissioning/`. Neither these reports nor SDK
publication establishes physical acceptance.
Battery, collision clearance and external controller ownership are not currently
automatically observed by this subscriber interface; operator checks remain
necessary. The handoff and tracking tolerance still require secured acceptance.

The earlier review below records the rationale and remaining hardware work;
claims of missing commissioning/tracking/stop infrastructure are superseded by
this implementation status.

## Biped-specific constraint

G1 is a biped, not a wheeled base. Any walking-stop adapter must preserve the
standing/balance controller: no damping command, motor disable, posture switch,
or leg command is authorized by this arm workflow. Zero observed translational
speed is not proof of balance or safe support. On-site setup must follow the
robot's approved operating procedure; this checklist does not prescribe an
improvised restraint. Arm authority release also requires a verified handoff to
the standing controller, rather than assuming zero authority is physically safe.

## Implemented execution protections

The executor now checks measured arm positions against the previous command
each cycle (including the start transition and final commanded frame), using
the existing 0.01 rad threshold. This is conservative, has no lag compensation,
and is not a hardware-validated tolerance. State freshness, finite positions,
joint limits, and model mode are also checked at the workflow boundary.

Start and playback loops abort if more than one 20 ms control period late,
rather than bursting catch-up commands. Initial state discovery has a separate
5 s timeout. Arm release and walking-stop callbacks run independently with a
shared 1 s cleanup wait budget; both are attempted on every exit. Failed or
timed-out cleanup retains the motion lease, and an original execution exception
is preserved. Timed-out daemon callbacks may continue running; do not reset the
lease or start another controller until operator recovery establishes safety.
Callback completion still does not establish a physical stop or safe handoff.

## Hardware acceptance remains pending

Keep `asset/g1_arm_contract.json` at `hardware_verified: false` until acceptance.
Speech acceptance and the earlier read-only preflight do not authorize movement.
No robot commands were sent during this review.

The target is the observed G1 29-DOF fake-hand model, firmware 1.5.4. The
read-only report from 2026-09-17T09:49:36Z is historical evidence, not fresh
state for a future run. Supported FSM values in that preflight also need review
for custom `rt/arm_sdk` playback; acceptance by the built-in action interface
does not by itself establish compatibility with custom joint commands.

## Offline candidate

`present_left` passes the existing loader: 101 samples at 25 Hz, lasting 4 s,
normalized to exactly 14 arm joints (DDS indices 15–28). Measured finite-difference
trajectory maxima are 1.284879 rad/s and 1.975351 rad/s², below the configured
1.5 rad/s and 3.0 rad/s² limits. These are sampled trajectory checks, not proof
of continuous-time actuator acceleration, collision clearance, or tracking.

The current executor adds a nominal 2 s start transition, commands at 50 Hz,
and uses provisional kp=40, kd=1. Both arms are controlled, including any
right-arm start-position transition, despite the action's name. Review both
arms' swept workspace. No reduced-speed commissioning mode is implemented;
do not describe the existing four-second playback as an accepted slow test.

## Implementation gates before a live test

- **Commissioning authorization:** normal execution requires
  `hardware_verified=true`, which is intentionally unavailable before acceptance.
  Design a separate narrowly scoped commissioning gate with explicit per-run
  operator confirmation and fresh preflight. Do not resolve this cycle by editing
  the flag, monkey-patching the contract, or directly calling the SDK helper.
- **Continuous state policy:** connect the read-only FSM/odometry checks to the
  live workflow. Currently `ActionService` relies on an injected stationary-base
  callback and checks arm faults/temperature; the composition root only provides
  dry-run wiring. Establish battery, active-controller/action ownership, and
  required localization policy, rejecting unavailable required evidence.
- **Tracking and timing:** checks and regression tests are now implemented as
  described above. Review tolerance, real DDS sampling/latency and scheduling
  policy before commissioning; fake tracking is not physical validation.
- **Stop and handoff:** validate independent bounded base-stop and arm-release
  paths. Independent bounded cleanup attempts are implemented, but the actual
  biped-safe adapters and handoff are not validated. Observe and report final state after normal
  completion, cancellation, stale state, and faults. Publishing zero authority
  is not evidence of a safe physical handoff or a confirmed stop.
- **Command contract and workspace:** review the exact firmware's authority-field
  convention and non-arm fields before publication. Current construction copies
  measured positions and zeroes non-arm gains/velocity/torque, with a special
  authority slot. Offline tests do not prove hardware semantics. Validate swept
  workspace and collision clearance for the transition and the whole action.
- **Regression coverage:** use injected fakes for changing FSM, stale/malformed
  state, tracking divergence, timing overruns, stop/release failures and final
  state reporting. Keep ordinary discovery and module demos hardware-free.

## Operator procedure after all implementation gates close

1. Record reviewed code revision, trajectory identity, model/firmware, arm-only
   mapping, gains, speed profile, workspace limits and abort thresholds. Require
   passing offline tests and a reviewed commissioning entry point first.
2. Have the on-site operator arrange an appropriate secured test area, clear both
   arms' workspace, and establish physical emergency-stop coverage. Exclude
   competing navigation, mapping, manual and arm controllers. Software stops
   never replace the physical emergency stop or the operator.
3. Obtain fresh subscriber evidence on the selected interface, including state
   ages, modes, battery, health and stationary base. Reject missing or invalid
   evidence. Check measured-to-start transitions against limits, not just the
   stored trajectory. Obtain explicit confirmation for this particular run.
4. Use the reviewed reduced-speed commissioning profile for one execution only;
   do not loop automatically. Abort on any interlock failure or operator request.
   Do not deliberately induce unsafe physical faults to test software paths.
5. Capture commanded/measured arm motion, maximum tracking error, timing,
   cancellation/release behavior and observed final state in ignored runtime
   output. Document operator observations and any uncertainty. Stop further
   testing if the handoff or final state cannot be established.
6. Only after reviewing the evidence, record acceptance and decide whether the
   exact model/firmware contract can be marked hardware-verified. A single
   successful gesture does not validate other trajectories or navigation.

Use only the scoped entry point above for commissioning; do not unlock general
execution or run the vendored full example (which includes waist joints).
