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
locomotion APIs.

Project conventions are recorded in `AGENTS.md`. Plans and current progress are
kept under `doc/`.
