# G1 Guide

G1 Guide is a staged guided-tour application for the Unitree G1. Development
starts with speech, adds stationary two-arm gestures, and introduces ROS 1
navigation only after the stationary workflow is verified.

## Safety boundary

The application starts in dry-run mode. Ordinary demos and unit tests never
connect to DDS, ROS, audio hardware, or a robot. Gesture playback will be limited
to explicitly allowlisted left- and right-arm joints; it must never command the
legs, waist, head, or hands.

The current dry-run application loads the recorder-compatible action archive at
`data/actions/trajectories/present_left.npz`, validates its model, timestamps,
joint limits, velocity, and acceleration, then normalizes it to exactly 14 arm
joints. Live arm publication remains locked until the target robot contract is
verified on secured hardware.

The action preflight is a separate subscriber-only path. It observes
`rt/lowstate`, the G1 HG FSM on `rt/sportmodestate`, and base odometry on
`rt/odommodestate`. It records the allowlisted arm motor health, supported action
FSM, and base velocity, and never constructs an arm or locomotion command client.

## Development

```bash
uv sync
uv lock --check
uv run python -m unittest discover -s tests -v
uv run python -m compileall app component util
```

The vendored Unitree SDK is an optional hardware dependency:

```bash
CYCLONEDDS_HOME="$PWD/third_party/cyclonedds/install" uv sync --extra hardware
```

The CycloneDDS installation must be compatible with the SDK's pinned Python
binding and include its development headers. Normal tests do not install this
extra.

Run the current safe application demo with:

```bash
uv run python -m app.application
```

The action preflight also defaults to a no-DDS safe mode:

```bash
uv run python -m app.action_preflight
```

On secured hardware, first confirm from trusted robot information that the target
matches the pinned 29-DOF fake-hand contract and record its firmware version.
Then run the subscriber-only check using the contract's canonical model ID:

```bash
CYCLONEDDS_HOME="$PWD/third_party/cyclonedds/install" \
uv run --extra hardware python -m app.action_preflight \
  --live --confirm-stationary --interface eth0 \
  --observed-model-id unitree_g1_29dof_rev_1_0_fake_hand \
  --observed-firmware-version '<version shown on the target robot>'
```

The default FSM topic is `rt/sportmodestate`, using the G1
`unitree_hg.msg.dds_.SportModeState_` schema observed on firmware 1.5.4. The
default velocity source is `rt/odommodestate`, using
`unitree_go.msg.dds_.SportModeState_`. Both topics and schemas are recorded in
the report.

The report is written atomically under `output/action_preflight/` and remains a
runtime artifact. A passing report does not enable arm playback or change
`hardware_verified`; the observed identity, DDS schema, gains, limits, and
physical emergency-stop coverage still require operator review.

The BytePlus TTS 2.0 demo remains offline unless both live flags are supplied:

```bash
CYCLONEDDS_HOME="$PWD/third_party/cyclonedds/install" \
uv run --extra hardware python -m app.tts_demo \
  --live --confirm-stationary --interface eth0 \
  --audio-name welcome_bilingual \
  --text "你好，welcome to the Unitree G1 guide."
```

The demo uses BytePlus TTS 2.0 Kian (`zh_male_m191_uranus_bigtts`) to generate
`data/tts/welcome_bilingual.wav`. The guide audio component then selects that
named file, and the G1 audio helper reads and streams its PCM frames.
`--confirm-stationary` confirms only a speech test. The path imports no arm or
locomotion APIs. Application workflows can pass one `threading.Event` through
the guide component to interrupt chunk pacing and call Unitree `PlayStop`;
separate playback calls always use separate stream IDs.

Project conventions are recorded in `AGENTS.md`. Plans and current progress are
kept under `doc/`.
