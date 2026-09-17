# Two-arm commissioning checklist

Reviewed: 2026-09-17T10:01:08Z

## Current decision: no live playback yet

This is a preparation checklist, not permission or an executable live-motion
runbook. Keep `asset/g1_arm_contract.json` at `hardware_verified: false`.
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
- **Tracking and timing:** `max_tracking_error_radians=0.01` is loaded but not
  enforced against measured motion by the executor. Implement and test tracking
  checks with a reviewed tolerance and sampling policy. Abort control-loop
  overruns instead of allowing rapid catch-up publication. Separate initial DDS
  discovery timeout from the 0.2 s sample-freshness limit in action execution.
- **Stop and handoff:** validate independent bounded base-stop and arm-release
  paths. Today a blocking base-stop callback can delay arm release; failures can
  also obscure the original error. Observe and report final state after normal
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

No live command is supplied here because the commissioning gate and required
interlocks are not yet implemented. Next work is offline implementation, not
asking the operator to unlock the present executor.
