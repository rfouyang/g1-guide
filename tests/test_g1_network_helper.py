from __future__ import annotations

import unittest
from unittest.mock import patch

from util.g1_helper.g1_network_helper import G1NetworkHelper


class G1NetworkHelperTests(unittest.TestCase):
    def test_ifconfig_output_selects_g1_network_interface(self) -> None:
        ifconfig_output = """\
lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536
        inet 127.0.0.1  netmask 255.0.0.0
wlan0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 10.0.0.25  netmask 255.255.255.0
eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 1500
        inet 192.168.123.42  netmask 255.255.255.0
"""
        with patch(
            "util.g1_helper.g1_network_helper.subprocess.run"
        ) as run_ifconfig:
            run_ifconfig.return_value.stdout = ifconfig_output

            network_interface = G1NetworkHelper.detect()

        self.assertEqual(network_interface, "eth0")
        run_ifconfig.assert_called_once_with(
            ["ifconfig"],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_legacy_ifconfig_address_is_supported(self) -> None:
        ifconfig_output = """\
enp2s0   Link encap:Ethernet  HWaddr 00:00:00:00:00:00
          inet addr:192.168.123.8  Bcast:192.168.123.255
"""
        with patch(
            "util.g1_helper.g1_network_helper.subprocess.run"
        ) as run_ifconfig:
            run_ifconfig.return_value.stdout = ifconfig_output

            network_interface = G1NetworkHelper.detect()

        self.assertEqual(network_interface, "enp2s0")

    def test_missing_g1_subnet_is_rejected(self) -> None:
        with patch(
            "util.g1_helper.g1_network_helper.subprocess.run"
        ) as run_ifconfig:
            run_ifconfig.return_value.stdout = (
                "eth0: flags=4163<UP>\n    inet 10.0.0.25\n"
            )

            with self.assertRaisesRegex(RuntimeError, "No network interface"):
                G1NetworkHelper.detect()


if __name__ == "__main__":
    unittest.main()
