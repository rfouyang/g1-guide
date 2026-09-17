from __future__ import annotations

import subprocess


class G1NetworkHelper:
    """Find the host interface connected to the G1 network."""

    NETWORK_PREFIX = "192.168.123."

    @classmethod
    def detect(cls) -> str:
        try:
            ifconfig_output = subprocess.run(
                ["ifconfig"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise RuntimeError("Unable to run ifconfig") from error

        current_interface = ""
        for line in ifconfig_output.splitlines():
            if line and not line[0].isspace():
                current_interface = line.split(maxsplit=1)[0].rstrip(":")
            has_g1_address = (
                f"inet {cls.NETWORK_PREFIX}" in line
                or f"inet addr:{cls.NETWORK_PREFIX}" in line
            )
            if current_interface and has_g1_address:
                return current_interface

        raise RuntimeError(
            f"No network interface found on {cls.NETWORK_PREFIX}*"
        )


def demo_g1_network_helper() -> None:
    sample_output = """\
eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 192.168.123.42  netmask 255.255.255.0
"""
    original_run = subprocess.run
    try:
        subprocess.run = lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=sample_output,
            stderr="",
        )
        assert G1NetworkHelper.detect() == "eth0"
    finally:
        subprocess.run = original_run
    print("G1 network helper: interface detection verified")


def main() -> None:
    demo_g1_network_helper()


if __name__ == "__main__":
    main()
