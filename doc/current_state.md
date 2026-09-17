# Current State

Updated: 2026-09-17T10:13:38Z

## Status

Phase 1 uses BytePlus TTS 2.0 rather than the G1 onboard `TtsMaker` voices. The
implementation is now file based: `BytePlusTtsHelper` generates a 16 kHz,
16-bit mono WAV under `data/tts/`; `TourAudioComponent` selects a named guide
audio; and `G1AudioHelper` reads the WAV and streams its PCM frames through
Unitree `AudioClient.PlayStream`.

The offline foundation for Phase 2 two-arm actions is now implemented. It reads
the native schema-2 NPZ output from `g1-action-recorder`, validates the pinned G1
model and safety limits, removes the three waist columns, and exposes an
immutable trajectory containing exactly the 14 allowlisted arm joints. The
application composition root validates `present_left` in dry-run mode. The
low-level `rt/arm_sdk` adapter is injectable and tested, but live execution is
locked by `hardware_verified: false`; no motion command has been sent. ROS and
navigation code have not been scaffolded.

A strictly read-only Phase 2 action preflight is implemented and has passed on
the target G1. Its low-level boundary constructs subscribers only for
`rt/lowstate`, the HG locomotion FSM on `rt/sportmodestate`, and the GO odometry
payload on `rt/odommodestate`; it has no publisher factory or command API. The
workflow records an independently observed model and firmware version, DDS
schemas and topics, state ages, FSM, motor count, all 14 allowlisted arm
positions, temperatures and faults, plus observed linear and yaw speed in an
atomic JSON report under `output/action_preflight/`. It does not change
`hardware_verified`.

The first live BytePlus-to-G1 test completed successfully on `eth0`: BytePlus
returned 217,256 PCM bytes and the G1 audio stream accepted the full playback.
The operator confirmed that Kian meets the desired voice quality. The refactored
file-based path has also completed its first live generation-and-playback test;
cancellation and repeated playback now have explicit offline behavior and tests,
and the live API exercise has completed. The operator confirmed satisfactory
cancellation and repeat playback on 2026-09-17; the Phase 1 speech gate is accepted.

When no DDS interface is supplied, `G1AudioHelper` now runs `ifconfig` and
selects the interface whose IPv4 address starts with `192.168.123.`. Callers can
still supply an interface explicitly when automatic detection is unavailable.

## Decisions Recorded

- Follow the four Robot Guide workflows: map building, POI management, task
  design, and task execution.
- Keep Gradio UI composition in `app/ui_guide/`. Organize business code into only
  `component/speech/`, `component/action/`, and `component/nav/`; do not create a
  platform-oriented `component/g1/` package.
- Put low-level BytePlus generation in `util/byteplus_tts_helper.py`. Keep the
  G1 network, audio, and action SDK boundaries under `util/g1_helper/`, with the
  multi-file action utilities under `util/g1_helper/g1_action_helper/`.
- Keep the guide-scene decision to play a named audio file in
  `component/speech/`.
- Put the lightweight application-side ROS 1 navigation client and navigation
  workflows in `component/nav/`.
- Name utilities `*_helper.py` or multi-file helper packages `*_helper/`.
- Vendor large non-ROS dependencies such as Unitree SDK2 Python under
  `third_party/unitree_sdk2_python/`, pinned to a documented upstream revision.
- Keep ROS-heavy packages such as FAST-LIO2, Livox drivers, `move_base`, TEB,
  velocity smoothing, and robot bringup under the separate catkin workspace
  `~/workspace/services/g1_ws/src/`.
- Use Ubuntu 20.04 and ROS Noetic. Nav2 and ROS 2 are not part of the selected
  navigation design.
- Follow the reference navigation chain: Livox input, FAST-LIO2 mapping and
  saved-map localization/relocalization, 3D-to-2D map/scan conversion,
  `move_base` with TEB, velocity smoothing, and a G1 `/cmd_vel` bridge.
- Preserve the action-recorder runtime layout under `data/actions/`: JSON source
  definitions in `definitions/` and compiled NPZ files in `trajectories/`.
- Store generated guide WAV files under `data/tts/`. Guide runtime components
  select them by stable file name rather than synthesizing speech directly.
- Develop from simple to difficult: TTS first, two-arm gesture playback second,
  and navigation last.
- Use one male voice that can read mixed Chinese and English naturally within the
  same utterance. Do not switch personas between language segments.
- Use BytePlus TTS 2.0 with Kian (`zh_male_m191_uranus_bigtts`) as the initial
  guide-voice candidate. Request `seed-tts-2.0`, set `explicit_language` to
  `zh-cn`, produce 16 kHz mono PCM, and play it through the G1 audio stream.
- Gesture playback may command only the left and right arms. It must never command
  the legs, waist, head, or hands.
- At each POI, require zero base velocity, speak and wait first, then run the
  ordered two-arm gestures and wait before continuing navigation.
- Keep only `README.md` and `AGENTS.md` as Markdown files at the project root.
  Store plans, architecture notes, runbooks, and progress records under `doc/`.
- Use this file, `doc/current_state.md`, as the canonical coding-progress and
  handoff record. Update it whenever implementation state, validation evidence,
  blockers, robot state, or next actions materially change.
- Use `uv` exclusively for Python dependency installation, locking, and command
  execution. Do not introduce pip or `requirements.txt` workflows.
- Write all project-owned Python code in object-oriented classes using composition
  and dependency injection rather than module-global state. Only module demos and
  `main()` remain as module-level functions.
- Give every project-owned implementation module a safe
  `demo_<module_name>()` function called by `main()`. Demos use fakes or read-only
  behavior by default and complement, rather than replace, the unit test suite.
- Store key variables and persistent configuration as class members. Keep
  important operation inputs explicit in methods, route secondary parameters
  through `**kwargs` with defaults, and avoid long function signatures.
- Prefer concise code with strong, readable logic and no redundant abstraction.
  Name computed return values with the domain concept before returning them so a
  reader understands what the value represents.

## Reference Review

The reference `rfouyang/robot-guide` repository was reviewed. Its feature split,
domain validation, execution events, preflight checks, atomic JSON persistence,
and fake-based tests are worth retaining. G1 Guide will correct its eager
credential-dependent construction, unauthenticated network-exposed controls,
concrete robot coupling, in-memory-only resume state, and incomplete speech
cancellation.

The reference unit suite was run in a temporary checkout. Without
`BYTEPLUS_API_KEY`, 11 tests failed during construction/import. With a dummy key,
all 77 tests passed. G1 Guide unit tests must remain independent of environment
secrets, ROS, DDS, audio devices, networks, and live hardware.

The `rfouyang/G1_guide` repository was also reviewed at commit
`7f3b43deaa30f9db3647284e78e8b4132fa34169`. It confirms the selected ROS 1
navigation topology: Ubuntu 20.04/Noetic, Livox MID360, FAST-LIO2,
`pointcloud_to_laserscan`, `move_base` with TEB, velocity smoothing, and a
Unitree velocity bridge. Its guide executor runs actions and speech in parallel;
our simpler initial behavior deliberately runs speech first and gesture second.
Its external trajectory path uses `.npy`, so the new `.npz` format requires its
own validated contract.

The reference reports an unresolved FAST-LIO localization problem during final
in-place rotation: map alignment can drift significantly while turning. This is
a release-blocking navigation test for G1 Guide, not a tolerance-setting detail.

The sibling `g1-action-recorder` repository was reviewed as the source contract.
It performs simulation playback only and does not publish physical robot
commands. Its schema-2 NPZ files contain 17 ordered upper-body columns: three
waist joints followed by seven left-arm and seven right-arm joints. The guide
normalizes these files to the 14 arm columns before they can reach an SDK
boundary. Unitree's high-level G1 example confirms `rt/lowstate`, `rt/arm_sdk`,
arm DDS indices 15–28, and the authority weight at unused slot 29. The recorder's
`mode_machine = 5` remains metadata to be verified on the target robot.

## Implementation Evidence

- Added the Python 3.10 `uv` project and generated `uv.lock`.
- Added a dry-run/live execution policy that requires explicit operator
  confirmation before hardware can be enabled.
- Added an exclusive, thread-safe motion lease for presentation, navigation,
  mapping, and manual control workflows.
- Added a composition root that constructs only the dry-run application.
- Vendored the official Unitree SDK2 Python source under
  `third_party/unitree_sdk2_python/` at revision
  `65691c8a8bc53b98d3976dba4dbf9d5d20b2e7f5` and declared it as the optional
  `hardware` extra. Its cloned Git metadata was moved to
  `/tmp/g1-guide-unitree-sdk2-python.git`; the pinned revision is recorded here.
- `uv lock --check` passed.
- All 8 unit tests passed with no credentials, network, ROS, DDS, audio device,
  or robot.
- Python compilation passed for `app`, `component`, and `util`.
- Safe demos passed for the application, execution policy, and motion lease.
- Vendored CycloneDDS tag `0.10.2` under `third_party/cyclonedds/` at revision
  `9995905bce6c4cf9f740d6438bbf7fcfd1c83dfd`, built it locally without changing
  system libraries, and successfully installed the locked `hardware` extra.
  Generated CycloneDDS install files are ignored. Its cloned Git metadata was
  moved to `/tmp/g1-guide-cyclonedds.git`.
- Replaced the direct in-memory speech pipeline with a file-based split:
  `BytePlusTtsHelper`, `G1AudioHelper`, and `TourAudioComponent`. The live demo
  generates `data/tts/<audio-name>.wav` before selecting and playing that file.
- Live TTS at 2026-09-15 19:02 CST initialized DDS on `eth0`, read volume `100`,
  and received response code `0` for: “你好，我是 G1 导览机器人。语音测试成功。”
- Mixed Chinese-English requests using onboard speaker IDs `0` and `1` were
  accepted at 2026-09-15 19:03 CST, but that path was superseded by the decision
  to use BytePlus TTS 2.0 for guide speech.
- Reviewed the official BytePlus TTS 2.0 documentation. It documents Kian as a
  General, male, steady, clear, versatile mid-range Chinese voice, and documents
  `explicit_language=zh-cn` as primarily Chinese with mixed Chinese-English
  support.
- All 16 current unit tests passed before the BytePlus live test. Compilation,
  fake demos, and offline safety demos also passed; source scans found no motion
  API in the speech path.
- Live BytePlus TTS 2.0 at 2026-09-15 19:13 CST generated 217,256 bytes of
  16 kHz mono PCM for “你好，welcome to the Unitree G1 guide. 很高兴为你服务。”
  The Unitree audio stream completed in approximately 6.8 seconds.
- Refactored speech at 2026-09-15 19:25 CST into utility-level file operations
  and scenario-level named selection. All 16 unit tests, compilation, safe demos,
  lock validation, and the no-motion-API scan passed.
- The refactored live path generated `data/tts/welcome_bilingual.wav` through
  BytePlus, then selected it by the name `welcome_bilingual`, read it from disk,
  and played it through G1 on `eth0`. The verified WAV is 216,432 bytes with
  16 kHz sample rate, one channel, 16-bit samples, and 108,194 frames.
- Reorganized `component/` at 2026-09-15 19:28 CST around the three guide
  capabilities only: `speech/`, `action/`, and `nav/`. Removed the former
  `g1/`, `common/`, and `navigation/` packages, updated every import and test,
  and reran all 16 tests, compilation, and safe demos successfully.
- Added `G1NetworkHelper` on 2026-09-16. It runs `ifconfig`, supports current and
  legacy IPv4 output formats, and selects the interface whose address starts
  with `192.168.123.`. The live TTS CLI uses automatic detection by default while
  retaining `--interface` as an override.
- All 21 unit tests, Python compilation, and the safe application, audio,
  component, and TTS demos passed after the interface-detection change. The
  current sandbox exposed only loopback through `ifconfig`, so target-network
  detection was verified with deterministic fixtures rather than live DDS.
  `uv lock --check` could not be repeated offline because the temporary cache
  lacks `setuptools` and `wheel`; dependency declarations and `uv.lock` were not
  changed.
- Reorganized G1 utilities under `util/g1_helper/`. Network selection is owned by
  `G1NetworkHelper`; audio playback uses it when no interface is supplied.
- Added NumPy as a locked runtime dependency through `uv add numpy`.
- Copied `present_left` and `concierge_speak_v1` definitions and NPZ files from
  `g1-action-recorder` into `data/actions/` without modification. Their NPZ
  SHA-256 values are respectively
  `873c65619a6b4721d9041427409fcfe41ef70f9dc663d8ec80365fdb99b13481` and
  `cd9bb04a6a589a4fe3d3b576fb50a8ec60c57696c7cb8a993ddd7987ff2171f9`.
- Added bounded, pickle-disabled NPZ loading, trajectory interpolation and motion
  metrics, the pinned 14-joint G1 arm contract, conservative action safety
  configuration, and the action trajectory/service workflow.
- `present_left` passes offline validation at 101 samples, 25 Hz, and 4 seconds.
  `concierge_speak_v1` is retained as recorder data but is rejected because its
  approximately 3.781 rad/s peak arm velocity exceeds the provisional 1.5 rad/s
  limit.
- Added an injectable `G1ArmSdkHelper` for `rt/lowstate` and `rt/arm_sdk`. Tests
  prove that only DDS indices 15–28 receive gains, indices 0–14 preserve measured
  positions with zero gains, and release publishes zero authority at slot 29.
- All 37 unit tests passed without credentials, network, ROS, DDS, audio hardware,
  or a robot after the action foundation was added. This includes a fake-clock
  full playback and cancellation test. No motion command was sent.
- The Phase 2 foundation baseline passed `uv sync`, `uv lock --check`, Python
  compilation of `app`, `component`, and `util`, and the safe application demo.
  At that earlier checkpoint, Git metadata was not functional, so direct
  whitespace and conflict-marker scans were used instead of `git diff --check`.
- Restored functional Git metadata, created the initial repository commit, and
  pushed `main` to `https://github.com/rfouyang/g1-guide` at commit `2fc6432`.
- Added a subscriber-only G1 action-state helper and action preflight workflow.
  The report fails closed on missing independent firmware observation, model or
  `mode_machine` mismatch, stale samples, motion errors, missing motors, arm
  faults, over-temperature, out-of-contract arm positions, or nonzero base
  velocity beyond the configured stationary thresholds.
- Added explicit stationary thresholds of 0.01 m/s linear speed and 0.01 rad/s
  yaw speed to the versioned action safety configuration.
- All 47 unit tests passed after the preflight work, including safe CLI
  interlocks, subscriber-only construction, malformed low- and motion-state
  rejection, stale state, aggregate safety failures, and atomic report
  persistence. Python compilation and project-owned diff checks also passed. An
  online `uv lock --check` resolved the unchanged metadata and confirmed that
  `uv.lock` is current.
- Added explicit speech cancellation from `TourAudioComponent` through
  `G1AudioHelper`. Cancellation interrupts chunk pacing, calls `PlayStop` in the
  existing cleanup path, and returns a receipt that distinguishes cancellation
  from completion. Each playback uses a new stream ID.
- All 50 unit tests passed after the speech update. New regressions cover
  cancellation after a submitted chunk, partial-byte evidence, `PlayStop`, fresh
  IDs and cleanup across repeated playback, and propagation of the shared
  cancellation signal through the guide component.
- The target G1 was observed on `eth0` at `192.168.123.161` from the development
  host `192.168.123.164`; the operator identified it as the 29-DOF fake-hand G1
  running firmware 1.5.4.
- Read-only DDS discovery established the firmware 1.5.4 state contract:
  `rt/sportmodestate` and `rt/lf/sportmodestate` publish
  `unitree_hg.msg.dds_.SportModeState_`, while `rt/odommodestate` publishes
  `unitree_go.msg.dds_.SportModeState_`. The pinned Python SDK lacked the HG
  sport-state class, so a project-owned low-level helper now implements the exact
  four-field XTypes contract and has a CDR round-trip regression test.
- Split initial DDS discovery from the 0.2-second freshness threshold. Preflight
  waits up to 5 seconds for the first complete state set while still rejecting
  any sample older than 0.2 seconds.
- The subscriber-only live preflight passed at 2026-09-17T09:49:36Z. It observed
  `mode_machine=5`, FSM 501/mode 0, 35 motor slots, all 14 arm faults at zero,
  maximum observed arm temperature 51 C, zero linear velocity, and yaw speed
  approximately 0.00107 rad/s. No control publisher was constructed and no
  motion command was sent. The ignored runtime report is
  `output/action_preflight/action_preflight_20260917T094936Z.json`.
- The post-integration default suite ran 54 tests: 53 passed and the optional
  CycloneDDS CDR test skipped because the default environment excludes hardware
  dependencies. With `--extra hardware`, all 54 tests passed, including that CDR
  regression. `uv sync`, `uv lock --check`, compilation of `app`, `component`,
  and `util`, `git diff --check`, and the four affected safe demos also passed.

Live audio acceptance evidence (2026-09-17T09:57:06Z): the existing
`welcome_bilingual.wav` was streamed on eth0 with cancellation requested after
1.5 seconds, followed by two complete repeats separated by two-second gaps.
Cancellation returned after 64,000 of 216,388 PCM bytes; each repeat submitted
all 216,388 bytes. All three stream IDs differed, and the test process exited
successfully. The operator subsequently confirmed that the listening result was
satisfactory with no issues, accepting the cancellation and repeat exercise.
No quantitative acoustic stop latency was measured.
The pinned SDK's `PlayStop` discards the RPC response
and returns zero unconditionally, so this run does not prove stop acknowledgement.
No arm or locomotion command was issued. Only this handoff document changed;
the previously recorded 54-test code baseline remains unchanged.

## Current Files

- `AGENTS.md` — repository conventions, structure, testing, and safety rules.
- `README.md` — project safety boundary and development commands.
- `pyproject.toml` and `uv.lock` — Python 3.10 project and locked dependencies.
- `app/application.py` — dry-run application composition root.
- `component/action/execution_policy.py` — fail-closed hardware authorization.
- `component/action/motion_lease.py` — exclusive workflow motion ownership.
- `component/speech/tour_audio_component.py` — named guide audio selection.
- `util/byteplus_tts_helper.py` — BytePlus TTS 2.0 WAV generation.
- `util/g1_helper/g1_network_helper.py` — automatic G1-interface discovery.
- `util/g1_helper/g1_audio_helper.py` — WAV validation and lazy G1 audio-only
  playback.
- `util/g1_helper/g1_action_helper/` — NPZ, numeric trajectory, and low-level
  `rt/arm_sdk` helpers.
- `component/action/action_trajectory.py` — recorder schema validation and strict
  17-source-joint to 14-arm normalization.
- `component/action/action_service.py` — dry/live policy, motion lease, base-stop
  checks, cancellation, transition, and fixed-rate action sequencing.
- `component/action/action_preflight.py` — subscriber-only action safety checks
  and atomic evidence reports.
- `asset/g1_arm_contract.json` — pinned robot model, joint limits, and DDS arm
  allowlist; live hardware verification is currently false.
- `config/action_safety.json` — provisional conservative arm-action limits.
- `data/actions/` — recorder definitions and compiled trajectories.
- `app/tts_demo.py` — explicit stationary live composition and CLI.
- `app/action_preflight.py` — safe-by-default read-only target-G1 preflight CLI.
- `util/g1_helper/g1_action_helper/action_state_helper.py` — low-state and
  separate HG FSM and GO odometry DDS subscriber boundary with no command
  publisher.
- `util/g1_helper/g1_action_helper/g1_sport_mode_state_helper.py` — exact
  four-field G1 HG sport-state IDL observed from target DDS XTypes.
- `tests/` — safe foundation unit tests.
- `third_party/unitree_sdk2_python/` — pinned upstream Unitree SDK source.
- `third_party/cyclonedds/` — pinned CycloneDDS 0.10.2 source.
- `doc/development_plan.md` — staged implementation plan and acceptance gates.
- `doc/current_state.md` — current progress, evidence, blockers, and next work.

## Session Checkpoint

- Added `app.arm_commissioning`: explicit live single-run entry point following
  the vendored arm7 SDK example, narrowed to 14 arms and no locomotion command
  client. The commissioning gate permits only `present_left` with confirmation
  and a continuous subscriber guard; contract verification remains false.
  Playback is 16 s, followed by an at-least-8 s return to measured starting arms
  and 3 s authority fade. Guard pins observed firmware 1.5.4 / FSM 501/0 /
  mode_pr 0. SIGINT/SIGTERM cancellation and before/after reports are wired.
  All 70 tests passed. No live motion was performed. See `doc/arm_acceptance.md`
  for the explicit command and operator prerequisites; physical handoff, battery,
  workspace and controller-ownership acceptance remain unresolved by unit tests.
- Implemented execution tracking checks against the previous arm command,
  workflow-level fresh/finite/in-range state checks, transition/playback overrun
  rejection, separate 5 s discovery timeout, and independent stop/release
  attempts with a 1 s cleanup budget. Cleanup failure retains the motion lease;
  original execution errors are preserved. All 63 tests, compile check,
  lock check and diff check passed. No physical execution occurred.
- The operator reiterated that G1 is a biped. The walking-stop callback must
  preserve standing/balance control, never disable legs or request damping.
  Callback completion and arm release do not prove a safe physical handoff.
  Actual live adapters, continuous FSM policy, commissioning entry point and
  observed final-state reporting remain unfinished.
- The 2026-09-17T10:01:08Z offline arm review produced
  `doc/arm_acceptance.md`. `present_left` dry-run passed: 101 samples, 4 s,
  maximum sampled velocity 1.284879 rad/s and acceleration 1.975351 rad/s².
  All 54 unit tests passed; application demo, `uv lock --check`, compile check,
  and `git diff --check` passed. No live DDS or motion command was used in this
  review; hardware verification remains false.
- The audio acceptance process exited at 2026-09-17 17:57 CST. No motion
  command was issued. Earlier diagnostic subscriber cleanup was not conclusively
  verified across process namespaces; do not assume all earlier readers exited.
- Phase 1 speech generation and one complete file-based G1 playback are working.
  The current reusable test asset is `data/tts/welcome_bilingual.wav`.
- Live TTS now discovers the G1-facing interface from the
  `192.168.123.0/24` address reported by `ifconfig`; operators can override it
  with `--interface`.
- The agreed component structure is fixed at `component/speech/`,
  `component/action/`, and `component/nav/`. Low-level BytePlus generation and
  G1 network/audio/action SDK details remain in their approved `util/*_helper.py`
  boundaries.
- Phase 1 speech is accepted: offline cancellation and repeat tests, the live
  API exercise, and operator listening confirmation are complete.
  The Phase 2 offline foundation is
  complete for `present_left`: recorder data,
  schema validation, 14-arm normalization, dry-run sequencing, cancellation,
  motion leasing, and the injectable SDK boundary are covered by tests.
- Live arm execution remains fail-closed. The target-robot read-only preflight
  passed for firmware 1.5.4, but physical playback has not been authorized or
  attempted and `hardware_verified` remains `false`.
- Target DDS compatibility is now established with separate HG FSM and GO
  odometry schemas; the preflight rejects unsupported action FSM values and
  non-stationary odometry.

## Next Actions

1. Review the implemented arm-only commissioning entry point with the operator;
   do not modify `hardware_verified` to perform the first test. It does not
   create a walking client or change standing mode.
2. Confirm stable standing, sufficient battery, no competing arm controller,
   emergency-stop coverage and clearance for both arms. Obtain fresh robot state and per-run
   confirmation for a secured `present_left` test with physical emergency-stop
   coverage. Only after evidence review may `hardware_verified` become true.
3. Retune or regenerate `concierge_speak_v1`; do not bypass its current velocity
   rejection.
4. Only after the stationary presentation is reliable, populate
   `~/workspace/services/g1_ws/src/` and reproduce FAST-LIO2 mapping,
   localization, and the reference ROS 1 navigation stack.

## Blockers

- Tracking limits, bounded arm cleanup, continuous FSM checks, before/after
  subscriber reports and a first-run commissioning gate are implemented.
  Physical arm handoff and tolerance validation remain pending; battery,
  collision clearance and external controller ownership need operator checks.
  See `doc/arm_acceptance.md`; the candidate is not ready for physical playback.
- The target identity and read-only state contract are observed, but the file
  contract remains explicitly unverified for command execution until a secured
  low-speed motion acceptance is reviewed on site.
- Provisional arm gains, velocity/acceleration limits, and motor temperature
  cutoff require secured hardware validation.
- The exact Livox model, extrinsics, and machine/network configuration are not yet
  recorded.
- FAST-LIO2 saved-map relocalization and rotation stability are not yet validated
  on the target robot.
- Audio cancellation and repeats have operator acceptance. The SDK still does
  not expose the actual stop RPC result; listening acceptance does not establish
  a guaranteed stop latency or programmatic stop acknowledgement.
- The definition of the guide's safe home position or docking behavior is not
  yet decided.
