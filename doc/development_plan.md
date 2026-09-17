# G1 Guide Development Plan

Updated: 2026-09-15 CST

## Goal

Build a supervised indoor guide application for Unitree G1 with three core
capabilities:

1. Convert configured text to speech and play it through the robot.
2. Load user-provided gesture trajectories from `.npz` files and safely replay
   them on the left and right G1 arms only.
3. Build a map with FAST-LIO2, localize in a saved map, and navigate the robot to
   named points of interest using the ROS 1 `move_base`/TEB stack.

At each point of interest, the robot stops walking, speaks first, performs the
configured two-arm gesture sequence second, and only then navigates to the next
point. Speech and gestures do not overlap in the initial implementation.

## Fixed Technical Decisions

- Application repository: `~/workspace/services/g1-guide/`.
- ROS workspace: `~/workspace/services/g1_ws/`.
- Operating environment: Ubuntu 20.04 with ROS Noetic.
- Mapping and LiDAR-inertial odometry: FAST-LIO2.
- Saved-map localization: the reference FAST-LIO2 localizer and relocalization
  service pattern.
- Navigation: ROS 1 `move_base`, global planner, TEB local planner, costmaps, and
  velocity smoothing.
- G1 base control: `/cmd_vel` output converted to bounded Unitree `LocoClient`
  commands by a watchdog-protected velocity bridge.
- G1 speech and gesture control: Unitree SDK2 Python, vendored under
  `g1-guide/third_party/unitree_sdk2_python/`. Low-level audio is wrapped in a
  utility helper; guide speech and gesture behavior belong in the `speech` and
  `action` component packages.
- Python dependencies: managed only with `uv`.
- Python implementation: OOP, concise methods, module demos, and isolated unit
  tests as defined in `AGENTS.md`.
- Development order is simple to difficult: speech, two-arm gesture playback,
  then mapping/localization and navigation.
- Gesture control is limited to the two arms. Legs, waist, head, and hands are
  never commanded by gesture code.

Nav2 and ROS 2 are not part of this design.

## Reference Repository Findings

The plan follows `rfouyang/G1_guide` at commit
`7f3b43deaa30f9db3647284e78e8b4132fa34169`.

Reuse these proven ideas:

- Livox MID360 input, FAST-LIO2 mapping/localization, 3D PCD plus 2D PGM/YAML
  map artifacts, `pointcloud_to_laserscan`, `move_base`, TEB, and velocity
  smoothing.
- Explicit relocalization against the selected PCD before navigation.
- A velocity bridge between ROS navigation output and Unitree high-level walking.
- One active motion/task slot, named safety interlocks, mock-by-default behavior,
  and lazy hardware imports.
- Guide execution as an explicit state machine with clear per-POI results. The
  new project changes the presentation step to sequential speech then gesture.
- A separate action library with validation and exclusive gesture execution.
- Final pose checking rather than assuming that sending a navigation goal means
  the POI was reached.

Do not copy these reference limitations:

- The reference gesture library uses `.npy`; this project uses the supplied
  `.npz` format and validates its full schema.
- Several copies of the same SDK/navigation sources appear in the reference.
  This project keeps one pinned SDK copy and one ROS workspace.
- Reference paths and network addresses are hard-coded in places. This project
  keeps machine-specific values in configuration.
- The reference reports substantial FAST-LIO localization drift during in-place
  final rotation. We must reproduce and resolve or bound that behavior before
  accepting POI navigation.
- The reference real DDS speech and external gesture paths were not completely
  validated on hardware. We treat both as new hardware acceptance work.
- The reference is a large REST platform. G1 Guide will implement only the
  interfaces needed by the operator UI and guide workflow.

Reference locations:

- https://github.com/rfouyang/G1_guide
- https://github.com/rfouyang/G1_guide/tree/7f3b43deaa30f9db3647284e78e8b4132fa34169/navigate/WK/G1Nav2D
- https://github.com/rfouyang/G1_guide/blob/7f3b43deaa30f9db3647284e78e8b4132fa34169/g1_api/g1_api/tour/executor.py
- https://github.com/rfouyang/G1_guide/blob/7f3b43deaa30f9db3647284e78e8b4132fa34169/g1_replay_min/replay_min.py

## Code and Runtime Structure

```text
~/workspace/services/g1-guide/
├── app/ui_guide/                  Gradio operator UI
├── component/
│   ├── speech/                    Named tour audio selection and sequencing
│   ├── action/                    Two-arm actions, safety, motion ownership
│   └── nav/                       Mapping, POIs, tasks, ROS navigation client
├── util/
│   ├── byteplus_tts_helper.py    BytePlus WAV generation
│   └── g1_helper/
│       ├── g1_network_helper.py  G1 subnet interface discovery
│       ├── g1_audio_helper.py    Low-level WAV streaming
│       └── g1_action_helper/     NPZ, trajectory, and arm_sdk helpers
├── third_party/
│   └── unitree_sdk2_python/       Single pinned upstream SDK copy
├── asset/                         Pinned robot/action contracts and maps
├── data/actions/
│   ├── definitions/              Recorder JSON source definitions
│   └── trajectories/             Compiled recorder .npz files
├── data/tts/                      Generated guide WAV files
├── config/                        Tasks and deployment configuration
├── doc/                           Plan, state, contracts, and runbooks
└── tests/                         ROS-free and hardware-free unit tests
```

```text
~/workspace/services/g1_ws/
├── src/
│   ├── fastlio2/
│   ├── livox_ros_driver2/
│   ├── movebase/
│   ├── pointcloud_to_laserscan/
│   ├── velocity_smoother_ema/
│   ├── tool/
│   ├── ros_map_edit/
│   ├── g1_guide_bringup/
│   └── g1_navigation_bridge/
├── build/                         Generated, ignored
└── devel/                         Generated, ignored
```

FAST-LIO2 and other upstream ROS packages keep their original package names.
Project-owned ROS packages use the `g1_` prefix. Local launch/configuration must
live in project-owned packages rather than modifying upstream files without a
documented patch.

## Navigation Pipeline

### Mapping mode

```text
Livox points + IMU
        -> livox_ros_driver2
        -> FAST-LIO2 map builder
        -> map.pcd + ground_map.pcd
        -> projected 2D occupancy grid
        -> grid.pgm + grid.yaml
```

Mapping is operator-controlled. Starting, finishing, and cancelling mapping are
exclusive operations. Finishing must verify that every artifact is newly written,
readable, non-empty, and associated with one map identity before publishing it to
the guide application.

### Localization and navigation mode

```text
Livox points + IMU -> FAST-LIO2 localizer -> slam_odom and TF
saved map.pcd      -> relocalization      -> global map alignment
grid.pgm/yaml      -> map_server          -> move_base global costmap
point cloud        -> LaserScan           -> move_base local costmap
POI pose           -> move_base + TEB      -> /cmd_vel
/cmd_vel           -> velocity smoother   -> G1 velocity bridge
G1 velocity bridge -> LocoClient.Move / StopMove
```

The expected reference frames are `map`, `local`, `slam_odom`, `body`, and
`base_link`. Phase 5 must record the actual TF tree and remove duplicate or
conflicting transforms before navigation.

The navigation result requires all of the following:

- `move_base` reaches a terminal success state;
- the live TF pose is within configured XY and yaw tolerances;
- localization remains initialized and fresh;
- the velocity bridge observes zero command and issues `StopMove`;
- the robot remains stable for a short arrival-settle interval.

If in-place rotation produces FAST-LIO drift, prefer POI yaw aligned with the
arrival direction while the root cause is investigated. Do not hide excessive
position drift by only widening tolerances.

## Speech Design

`BytePlusTtsHelper` converts configured text into a 16 kHz, 16-bit mono WAV file
under `data/tts/`. `G1AudioHelper` validates and reads that file before streaming
its PCM frames. `TourAudioComponent` owns the guide-scenario decision to play a
specific named audio asset.

- Important TTS inputs: text and destination WAV path.
- Important guide input: the configured audio name.
- Validate empty text, file names, paths, WAV format, and file presence before
  contacting G1 audio.
- Write generated WAV files atomically so a partial response is never published.
- Check every cloud and SDK return code and expose an actionable error.
- Keep stable audio names in task configuration so a tour can reuse pre-generated
  files without calling BytePlus during playback.
- A stop request must stop playback when supported and must never delay the base
  stop path.

## NPZ Gesture Design

The supplied files use `g1-action-recorder` schema version 2. Each archive has
the exact arrays `schema_version`, `action_name`, `robot_model_id`, `fps`,
`joint_names`, `timestamps`, `joint_positions`, `keyframe_sample_indices`,
`source_pose_names`, `keyframe_hold_seconds`, and `max_tracking_error`.

Recorder positions have 17 ordered columns: three waist joints, seven left-arm
joints, and seven right-arm joints. The loader accepts only that exact source
order, validates it, then creates a new immutable runtime trajectory containing
only the 14 arms. Waist columns never enter the SDK command API.

`ActionTrajectory` and `ActionService` validate before any command is
published:

- required NPZ keys and schema version;
- numeric dtype with `allow_pickle=False`;
- two-dimensional position matrix and non-empty frame count;
- ordered joint names or an explicitly documented canonical order;
- timestamps or a positive sample frequency;
- finite positions and strictly increasing timestamps;
- exact G1 model/DOF compatibility;
- an immutable allowlist containing only the left and right arm joints;
- rejection of every trajectory containing leg, waist, head, or hand joints;
- URDF joint limits plus configured velocity and acceleration limits;
- safe transition from measured arm state to the first frame;
- safe final pose and arm-control handoff behavior.

Playback uses one measured-state subscriber and one fixed-rate publisher. It
starts from the measured pose, ramps control authority conservatively, follows
the trajectory using monotonic time, watches fresh motor state and cancellation,
holds measured position on failure, then returns to the configured guide-safe
pose before releasing arm control.

If the Unitree command message contains slots for the full robot, gesture code
must preserve measured non-arm positions and apply no control authority to those
slots. Unit tests verify the exact two-arm motor IDs for the selected G1 model and
fail if a leg, waist, head, or hand motor enters a command.

Gestures run only while base velocity is observed at zero. A gesture failure
keeps the base at the POI until an operator verifies arm state.

## Guide Task and Execution Model

```text
GuideTask
├── task_id
├── name
├── map_id
├── revision
└── stops[]
    ├── poi_id
    ├── poi_name
    ├── pose
    ├── speech_text
    └── gesture_ids[]
```

Execution sequence:

```text
preflight
  -> navigate to POI
  -> verify arrival and zero base velocity
  -> speak and wait for speech completion
  -> run ordered two-arm gestures and wait for completion
  -> dwell if configured
  -> repeat
  -> finish at the configured safe POI or remain at the final POI
```

Preflight verifies the selected map, successful relocalization, fresh TF and
odometry, healthy navigation nodes, velocity bridge heartbeat, G1 DDS state,
walking mode, battery/fault state, gesture validation, speech readiness, motion
lease, and operator confirmation.

Only one mapping, navigation, manual-motion, or guide operation may own the robot
at a time. Stop bypasses queued work and commands base stop before two-arm
gesture/audio cleanup.

## Delivery Milestones

### Phase 0 — Scaffold and safe test foundation

- Add `pyproject.toml`, `.python-version`, `uv.lock`, `.gitignore`, and `README.md`.
- Vendor and pin Unitree SDK2 Python once under `third_party/` and declare its
  local path/dependencies through `uv`.
- Implement OOP domain models, repositories, fake components, motion ownership,
  and the application composition root.
- Add one safe `demo_<module>()` plus `main()` to every implementation module.
- Record the exact G1 model, 23/29 DOF mode, firmware, SDK version, compute host,
  network interface, and robot address.

Exit gate: all demos and tests run through `uv`, with hardware operations disabled
by default and no ROS dependency.

### Phase 1 — Make the robot talk

- Implement the OOP `BytePlusTtsHelper`, `G1AudioHelper`, and
  `TourAudioComponent` with fake boundaries.
- Synthesize with BytePlus TTS 2.0 using the documented Kian male voice,
  `zh_male_m191_uranus_bigtts`, and mixed Chinese-English mode.
- Save BytePlus PCM as a 16 kHz, 16-bit mono WAV under `data/tts/`, then read the
  selected file and stream its PCM frames through Unitree `AudioClient.PlayStream`.
  Do not use the onboard language-specific `TtsMaker` voices for guide speech.
- Validate cloud authentication, speaker authorization, DDS initialization,
  repeated playback, completion reporting, cancellation, and error reporting.
- Add a minimal CLI/demo that accepts text and an audio name, generates the WAV,
  then plays the named file only after an explicit operator command.
- Keep this phase free of gesture and navigation imports so speech can be tested
  independently.

Exit gate: the stationary G1 speaks repeated test phrases reliably, and speech
failure or cancellation never produces a motion command.

### Phase 2 — Validate actions without moving hardware

- Preserve the recorder data layout and validate the exact schema-2 arrays.
- Read NPZ files with `allow_pickle=False`, bounded compressed/decompressed size,
  finite-value checks, and actionable failures.
- Normalize the known 17-joint recorder source order to the immutable 14-arm
  allowlist at DDS indices 15–28.
- Enforce position, velocity, acceleration, tracking-error, duration, and
  transition checks from versioned configuration.
- Test the injected arm SDK boundary to prove no non-arm motor receives gains or
  control authority.
- Validate `present_left` through the application composition root without
  publishing DDS commands. Retain but reject more aggressive actions until they
  are regenerated or safely retuned.

Exit gate: completed for `present_left`; malformed or unsafe files fail before
constructing or calling a real SDK client, and tests prove that no forbidden
motor ID can receive control authority.

### Phase 3 — Play two-arm gestures on the stationary G1

- Read measured joint state before playback and enter the trajectory with a
  conservative, bounded transition.
- Confirm the recorder metadata assumption `mode_machine = 5` on the target G1;
  it is not accepted as hardware evidence by itself.
- Play at a fixed rate and reduced speed, commanding only allowlisted left/right
  arm joints.
- If the verified Unitree message is full-body, preserve measured non-arm targets
  and apply zero control authority to legs, waist, head, and hands.
- Implement cancellation, hold, timeout, and return-to-guide-safe-pose behavior.
- Begin with one short trajectory while the robot is stationary and secured, with
  the physical emergency stop ready.

Exit gate: one short two-arm gesture repeats safely; logs and tests demonstrate
that legs and waist are never commanded or changed by the guide application.

### Phase 4 — Stationary presentation workflow

- Model a presentation as speech text followed by ordered gesture IDs.
- Enforce the sequence: speak, wait for speech completion, perform the two-arm
  gestures, then report completion.
- Add cancellation and fault tests for every boundary between speech and action.
- Add the minimum task editor/executor UI needed to rehearse presentations while
  the robot remains stationary.

Exit gate: repeated stationary presentations complete in strict speech-then-action
order, and every failure leaves the arms and base in a safe observed state.

### Phase 5 — Reproduce ROS mapping and localization

- Create the ROS 1 Noetic catkin workspace at `~/workspace/services/g1_ws/`.
- Import and pin the reference-compatible Livox, FAST-LIO2, relocalization, and
  supporting ROS packages under `g1_ws/src/`.
- Add machine-specific configuration in `g1_guide_bringup`, build with
  `catkin_make`, and record the node/topic/service/action/TF graph.
- Reproduce mapping, 3D and 2D map saving, localization, and relocalization.
- Diagnose the reference's final in-place-rotation localization drift using bags
  and TF logs before enabling autonomous navigation.

Exit gate: a saved map loads and the stationary robot repeatedly relocalizes with
bounded position and yaw variation, including during controlled rotation tests.

### Phase 6 — Validate navigation by itself

- Bring up `map_server`, point-cloud-to-scan conversion, costmaps, `move_base`,
  TEB, and velocity smoothing using the reference ROS 1 architecture.
- Implement the bounded, dead-man G1 velocity bridge and verify zero velocity on
  cancellation, stale input, ROS node loss, and process exit.
- Tune footprint, speed/acceleration limits, obstacle distances, goal tolerances,
  and recovery behavior before adding presentation behavior.
- Run supervised A-to-B-to-A trials with speech and arm action disabled.

Exit gate: ten supervised runs succeed with acceptable final-pose error and no
stale-command movement; all stop and fault paths are verified.

### Phase 7 — Full guide workflow and operator UI

- Build Map, POI, Task Design, and Task Execution tabs.
- Record POIs from the current localized pose and bind them to a map identity.
- At each POI, verify arrival and zero base speed, speak and wait, then execute
  ordered two-arm gestures and wait before navigating again.
- Show robot, localization, navigation, speech, and gesture readiness in one
  preflight view.
- Keep Stop always visible and outside the normal UI queue.
- Test blocked paths, localization loss, ROS restart, DDS loss, low battery,
  gesture rejection, motor fault, TTS failure, process restart, and user stop.
- Persist checkpoints with task revision and map identity; write deployment,
  operator, recovery, and mapping runbooks.

Exit gate: an operator can create and dry-run a tour, then complete a supervised
multi-POI hardware guide; the release checklist is approved for the exact robot,
map, firmware, sensor configuration, and operating site.

## Immediate Next Work

1. Scaffold the OOP Python application and fake components with `uv`.
2. Implement and validate TTS on the stationary G1, with all motion disabled.
3. Obtain one representative `.npz` for read-only inspection and lock the exact
   two-arm joint allowlist for the robot model.
4. Validate one short two-arm gesture on secured hardware, never commanding legs
   or waist.
5. Rehearse the strict speech-then-action presentation workflow while stationary.
6. Only then populate `~/workspace/services/g1_ws/src/`, reproduce FAST-LIO2
   mapping/localization, and validate the reference ROS 1 navigation stack.
