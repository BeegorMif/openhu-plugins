import asyncio
import json
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, patch

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(PLUGIN_DIR))
sys.path.insert(0, os.path.join(REPO, "plugins", "org.openhu.can", "lib"))
sys.path.insert(0, os.path.join(REPO, "plugins", "org.openhu.can", "bin"))
sys.path.insert(0, os.path.join(PLUGIN_DIR, "bin"))

import canbus  # noqa: E402
import display  # noqa: E402


class FakeApi:
    def __init__(self):
        self.handlers = []
        self.published = []
        self.requests = []

    def on(self, pattern, callback):
        self.handlers.append((pattern, callback))

    async def publish(self, topic, **data):
        self.published.append((topic, data))

    async def request(self, method, **params):
        self.requests.append((method, params))
        return {}

    async def safe(self, coroutine):
        return await coroutine


class IgnitionTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        profile_path = os.path.join(REPO, "plugins", "org.openhu.can", "profiles", "bmw_f20.json")
        with open(profile_path, encoding="utf-8") as file:
            self.profile = canbus.Profile(json.load(file))
        self.api = FakeApi()
        self.plugin = display.DisplayPlugin(self.api, {
            "ignitionPowerOff": True,
            "ignitionDelaySeconds": 300,
        })
        self.save_config = patch.object(display, "save_config")
        self.save_config.start()
        self.addCleanup(self.save_config.stop)

    async def asyncTearDown(self):
        if self.plugin.shutdown_task is not None:
            self.plugin.shutdown_task.cancel()
            await asyncio.gather(self.plugin.shutdown_task, return_exceptions=True)

    async def feed_bmw(self, byte):
        changed, _, _ = self.profile.feed(0x130, bytes([byte]))
        if "can.ignition" in changed:
            await self.plugin.on_can("can.ignition", changed["can.ignition"])

    async def test_bmw_f20_ignition_off_blacks_screen_and_on_cancels(self):
        await self.feed_bmw(0x05)  # KL R and KL 15 active
        self.assertEqual(self.plugin.ignition_state, "ON")
        self.assertTrue(self.plugin.config["ignitionEverOn"])

        await self.feed_bmw(0x00)  # both terminals off
        self.assertTrue(self.plugin.ignition_blackout)
        self.assertTrue(self.plugin.shutdown_deadline > 0)
        self.assertIn(("ui.overlay.show", {"id": display.PLUGIN_ID}), self.api.requests)
        pending = self.plugin.shutdown_task
        self.assertIsNotNone(pending)

        await self.feed_bmw(0x01)  # accessory returns before timeout
        await asyncio.sleep(0)
        self.assertEqual(self.plugin.ignition_state, "ON")
        self.assertFalse(self.plugin.ignition_blackout)
        self.assertEqual(self.plugin.shutdown_deadline, 0)
        self.assertTrue(pending.cancelled())
        self.assertIn(("ui.overlay.hide", {"id": display.PLUGIN_ID}), self.api.requests)

    async def test_timer_expiry_requests_system_poweroff(self):
        await self.feed_bmw(0x01)
        await self.feed_bmw(0x00)
        self.plugin.shutdown_deadline = time.time() - 1
        self.plugin.config["shutdownDeadline"] = self.plugin.shutdown_deadline
        with patch.object(self.plugin, "request_poweroff", new_callable=AsyncMock) as poweroff:
            await self.plugin.power_off_when_due(self.plugin.shutdown_deadline)
        poweroff.assert_awaited_once_with()

    async def test_can_unavailable_is_not_ignition_off(self):
        await self.feed_bmw(0x01)
        await self.plugin.on_can("can.ignition", {"available": False})
        self.assertEqual(self.plugin.ignition_state, "ON")
        self.assertFalse(self.plugin.ignition_blackout)
        self.assertEqual(self.plugin.shutdown_deadline, 0)

    async def test_auto_poweroff_is_opt_in(self):
        self.plugin.config["ignitionPowerOff"] = False
        await self.feed_bmw(0x01)
        await self.feed_bmw(0x00)
        self.assertEqual(self.plugin.ignition_state, "OFF")
        self.assertFalse(self.plugin.ignition_blackout)
        self.assertEqual(self.plugin.shutdown_deadline, 0)


if __name__ == "__main__":
    unittest.main()
