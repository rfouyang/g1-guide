# Repository Guidelines

## Project Direction

Build a Python application for designing and running guided tours on a Unitree
G1. Preserve the reference application's four workflows: map building, POI
management, task design, and task execution. Treat the G1, navigation stack,
speech system, and UI as separate boundaries; do not copy Slamware- or
Tianyi-specific assumptions into the domain model.

## Project Structure

- `app/ui_guide/` contains Gradio composition, view state, and callbacks.
- `component/` has exactly three feature packages: `speech/`, `action/`, and
  `nav/`. Do not group business code by robot platform, so do not add a `g1/`
  component package.
- `component/speech/` contains guide-scenario speech behavior such as selecting
  and playing a named tour audio asset. It must not contain generic TTS
  generation, WAV reading, or raw G1 audio streaming details.
- `component/action/` contains gesture workflows, action safety policy, and the
  shared physical-motion lease.
- `component/nav/` contains application-side navigation workflows and the client
  for APIs exposed by the separate ROS 1 workspace. Do not place ROS packages or
  ROS-heavy nodes in this repository.
- `third_party/` contains large vendored upstream packages such as
  `third_party/unitree_sdk2_python/`. Project code must access them through a
  narrowly scoped helper or component boundary rather than importing them from
  UI or unrelated business workflows.
- `util/` contains reusable utility behavior grouped in helper classes. This
  includes BytePlus TTS file generation and the low-level G1 network, audio, and
  two-arm SDK boundaries under `util/g1_helper/`. Utility modules must be named
  `*_helper.py`; a multi-file utility package must be named `*_helper/`.
- `config/` contains versioned, human-readable task configuration.
- `asset/` contains authoritative input maps and pinned robot/action metadata.
- `data/` contains runtime assets consumed by guide components:
  `data/tts/` stores generated guide WAV files, while `data/actions/definitions/`
  and `data/actions/trajectories/` preserve the action-recorder layout.
- `output/` contains generated maps, logs, and snapshots and stays ignored.
- `tests/` mirrors behavior under test. Hardware tests must be isolated and
  opt-in.
- Only `README.md` and `AGENTS.md` may be Markdown files at the repository root.
  Put all other Markdown documentation under `doc/`.
- `doc/current_state.md` is the canonical implementation-progress handoff. Update
  it after material code changes, validation runs, hardware observations,
  blockers, or changes to the next actions.

## ROS 1 Workspace

Keep ROS-heavy software in the separate catkin workspace
`~/workspace/services/g1_ws/`, not inside `g1-guide`:

```text
~/workspace/services/g1_ws/
├── src/
│   ├── g1_navigation_bridge/
│   ├── g1_guide_description/
│   ├── g1_guide_bringup/
│   ├── fastlio2/
│   ├── livox_ros_driver2/
│   ├── movebase/
│   ├── pointcloud_to_laserscan/
│   ├── velocity_smoother_ema/
│   └── <other ROS packages>/
├── build/       # generated; never commit
└── devel/       # generated; never commit
```

Target Ubuntu 20.04 and ROS Noetic to match the reference navigation framework.
Follow normal ROS 1 package conventions under `g1_ws/src`: one catkin package per
directory with `package.xml` and `CMakeLists.txt`. Put launch files in `launch/`,
runtime configuration in `config/` or `param/`, nodes/scripts in `src/` or
`scripts/`, URDF/Xacro in `urdf/`, RViz configuration in `rviz/`, and package
tests in `test/`.

Project-owned ROS packages use the `g1_` prefix. Preserve third-party package
names and upstream layouts, including packages such as FAST-LIO. Pin every
third-party ROS repository by revision in a workspace manifest or documented
import file; do not edit vendored upstream sources casually. Keep local
integration, launch, configuration, and patches in project-owned `g1_*`
packages.

Build the ROS workspace from its root with `catkin_make`, source
`devel/setup.bash`, and keep `build/` and `devel/` out of version control. This
application must communicate with ROS through the small interfaces in
`component/nav/` so ordinary `g1-guide` unit tests remain ROS-free.

Keep UI code thin. UI modules may translate errors and render state, but workflow
decisions belong in `component/`. Low-level BytePlus, DDS, and audio-file details
belong in the approved `util/*_helper.py` boundaries; application-side ROS
navigation details belong in `component/nav/`.

## Python Style

- Target Python 3.10 or the version pinned by `.python-version`.
- All project-owned Python code is object-oriented. Every non-empty implementation
  module defines one or more focused classes. Put business behavior, utility
  behavior, framework callbacks, factories, serialization, and mutable state on
  classes; use composition and dependency injection instead of module-global
  state. The only module-level functions are the required `demo_<module_name>()`
  and `main()` entry points.
- Use four-space indentation and standard PEP 8 naming: `snake_case` for modules,
  functions, and variables; `PascalCase` for classes; `UPPER_SNAKE_CASE` for
  constants.
- Start new Python modules with `from __future__ import annotations`.
- Group imports as standard library, third party, then local imports.
- Prefer `pathlib.Path` to string path manipulation.
- Add type hints to public interfaces and concise docstrings where intent or
  safety behavior is not obvious. Avoid narrating straightforward code.
- Use dataclasses for stable domain values and explicit state records. Validate
  untrusted dictionaries at file, UI, SDK, and ROS boundaries before converting
  them to domain objects.
- Keep functions focused and names behavior-oriented. Prefer early validation and
  actionable exceptions over deeply nested control flow.
- Prefer simple, compact code with strong control flow. Do not add abstractions,
  branches, wrappers, or repeated transformations that do not clarify behavior or
  enforce a real boundary.
- Optimize for readability rather than the fewest possible lines. Give computed
  return values a meaningful local name that explains the domain concept, then
  return that value. The name must add information; avoid placeholders such as
  `data`, `value`, or `temp` when a more specific concept is known. `result` is
  acceptable for generic calculations, but prefer a domain name when available.
- Keep each intermediate variable close to its use. Do not split an obvious
  expression into many mechanical steps or repeat the same computation merely to
  create names.
- Store key collaborators, configuration, and state as class member variables
  such as `self.client`, `self.options`, and `self.current_task`; do not repeatedly
  pass key variables through method call chains.
- Keep important, operation-defining inputs explicit in the method signature.
  Put secondary or rarely changed tuning parameters in `**kwargs`, resolving each
  with a documented default inside the method.
- Do not create long parameter lists. When a signature starts accumulating
  arguments, decide whether each value is persistent class state, an important
  explicit operation input, or a secondary `**kwargs` option. Use a dedicated
  dataclass when several values form one cohesive domain object.
- Validate optional keyword values before use and keep their names consistent
  across components. Safety-critical choices and required identifiers must never
  be hidden in `**kwargs`.
- Use UTC ISO-8601 timestamps in persisted data and include a schema version.
- Use `loguru` structured messages at device and workflow boundaries. Never log
  secrets, authorization tokens, or unbounded raw sensor data.

## Module Demos

Every project-owned Python implementation module must provide a safe,
deterministic `demo_<module_name>()` function and a `main()` entry point that
calls it:

```python
def demo_robot_state() -> None:
    service = RobotStateService(client=FakeRobotStateClient())
    snapshot = service.snapshot()
    assert snapshot.is_fresh
    print(snapshot)


def main() -> None:
    demo_robot_state()


if __name__ == "__main__":
    main()
```

Treat the demo as a small executable test case: exercise the module's primary
behavior, check at least one expected result, and print a concise human-readable
result. It does not replace full assertions and edge-case coverage in `tests/`.
Demos must default to fakes or read-only behavior and must not require credentials,
ROS, DDS, network access, audio hardware, or robot motion. A physical hardware
demo requires an explicit live-mode flag and operator confirmation.

Empty `__init__.py` package markers, test modules, generated files, ROS launch
files, and code under `third_party/` are exempt from the per-module demo rule.

Preferred method shape:

```python
class NavigationService:
    def __init__(self, client: NavigationClient) -> None:
        self.client = client
        self.default_timeout = 300.0
        self.default_speed_ratio = 0.3

    def navigate(self, destination: Pose, **kwargs: object) -> NavigationResult:
        timeout = float(kwargs.get("timeout", self.default_timeout))
        speed_ratio = float(
            kwargs.get("speed_ratio", self.default_speed_ratio)
        )
        return self.client.navigate(
            destination,
            timeout=timeout,
            speed_ratio=speed_ratio,
        )
```

Here `client` and defaults are key member variables, `destination` is the
important operation input, and timeout/speed tuning remains optional without
lengthening the public signature.

Preferred computed-return shape:

```python
class RouteMetrics:
    def total_distance(self, first_leg: float, second_leg: float) -> float:
        route_distance = first_leg + second_leg
        return route_distance
```

Avoid a bare computed return when it hides the meaning of the value:

```python
class RouteMetrics:
    def total_distance(self, first_leg: float, second_leg: float) -> float:
        return first_leg + second_leg
```

## Architecture and Dependencies

- Assemble dependencies in one application composition root. Do not construct
  network, DDS, ROS, audio, or credential-dependent clients at module import time.
- Do not put guide workflows, repositories, services, or domain models in
  `util/`. Those responsibilities belong in `component/`. Approved low-level
  boundaries include `BytePlusTtsHelper`, `G1AudioHelper`, and the narrowly
  scoped helpers under `util/g1_helper/g1_action_helper/`. Components own action
  validation, safety policy, motion leasing, and scenario decisions.
- Keep vendored dependencies under `third_party/<upstream_name>/`, preserving the
  upstream directory structure, license, notices, and history or pinned revision.
  Do not mix project-owned modules into a vendored package or make casual local
  edits to upstream code. Carry necessary changes as explicit patches or in a
  project-owned component wrapper, and document the upstream URL and revision.
- Do not copy a third-party package into multiple locations. Exclude its generated
  files, build output, virtual environments, and caches from version control.
- Depend on small injectable interfaces for robot state, base motion, navigation,
  mapping, arm actions, and speech. Unit tests must be able to replace each one
  with an in-memory fake.
- Keep the task model platform-neutral: a task is an ordered list of stops; a stop
  references a POI and contains speech plus an ordered list of optional actions.
- Keep one owner for physical execution. Mapping, navigation, manual motion, and
  task execution must share the same motion lease/lock.
- Make cancellation explicit and propagate one cancellation signal through every
  long-running operation. Timeouts use `time.monotonic()`.
- Persist configuration atomically with write-to-temporary-file plus
  `os.replace`. Preserve unknown/newer schemas by rejecting them clearly rather
  than silently rewriting them.
- Keep dependency declarations minimal and the lockfile synchronized. Do not add
  packages that duplicate the Python standard library.

## Dependency Management

Use `uv` exclusively for project Python environments, dependency changes, and
lockfile updates:

- `uv sync` creates or updates the locked development environment.
- `uv add <package>` adds a runtime dependency.
- `uv add --dev <package>` adds a development dependency.
- `uv remove <package>` removes a dependency.
- `uv lock --check` verifies that `uv.lock` matches `pyproject.toml`.
- `uv run python ...` runs project commands in the managed environment.

Do not use `pip install`, maintain a `requirements.txt`, or manually edit
`uv.lock`. When vendored Python source is imported at runtime, declare it as a
local path dependency in `pyproject.toml` and let `uv` install its Python
dependencies. ROS packages and system dependencies continue to use their
documented ROS/system workflows.

## Testing and Verification

- Use Python's `unittest` framework unless the repository deliberately migrates
  the whole suite.
- Name files `test_*.py`, classes `*Tests`, and methods `test_<behavior>`.
- Unit tests must run without `.env`, API keys, network access, ROS, DDS, audio
  hardware, or a robot. Constructor injection is required when a boundary would
  otherwise make this impossible.
- Add regression tests for malformed SDK/ROS data, stale state, timeouts,
  cancellation, reconnects, task migration, and every safety interlock.
- Mark hardware-in-the-loop tests explicitly and require both an opt-in flag and
  operator confirmation. Never move hardware during ordinary test discovery.
- Before handing off code, run the full unit suite, compile check, and repository
  diff check. Add formatter, linter, and type-check commands here once selected.

Expected baseline commands after scaffolding:

```bash
uv sync
uv lock --check
uv run python -m unittest discover -s tests -v
uv run python -m compileall app component util
git diff --check
```

## Robot Safety and Security

- Default to fake/dry-run mode. Live motion requires an explicit deployment mode,
  a fresh robot-state preflight, and per-run operator confirmation.
- A web checkbox is not an authorization boundary. Bind the UI to localhost by
  default; require authentication and a trusted network before exposing it.
- Validate model/DOF, firmware capabilities, DDS interface, state freshness,
  locomotion mode, battery, motor faults, temperatures, localization, and active
  actions before movement.
- Enforce conservative velocity, acceleration, arm-speed, and workspace limits in
  code. Reject commands outside the configured G1 model contract.
- Gesture playback may command only the explicitly mapped joints of the left and
  right arms. Never command or alter leg, waist, head, or hand joints. If a vendor
  message contains full-body fields, preserve measured non-arm positions and set
  their control authority to zero according to the verified SDK contract.
- Keep an immutable two-arm joint allowlist for each supported G1 model. Reject a
  trajectory or command containing any joint outside that allowlist before
  hardware publication.
- Stop commands bypass normal queued work. On cancellation or stale state, stop
  base motion and arm action immediately, stop audio when supported, then report
  the robot's observed final state.
- Never imply that a software stop replaces the physical emergency stop or an
  on-site operator.
- Never commit `.env`, credentials, network-specific secrets, generated output,
  or mutable live-robot state.

## Commits and Pull Requests

Use short, imperative, sentence-case subjects such as `Add G1 locomotion
preflight`. Keep commits focused and exclude unrelated runtime artifacts. Pull
requests should explain user-visible behavior, list verification commands, link
the relevant issue, include screenshots for UI changes, and call out robot setup,
firmware assumptions, and safety impact.
