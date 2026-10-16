"""The logger process against a fake OpenHU bus (WebSocket, same protocol as OpenHU's API): vehicle data in, trips
and samples out through logger.query / logger.result, settings through logger.command, logger.live and
logger.state published, recordings, delete all data, restart."""

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(TESTS, "..", "bin"))
sys.path.insert(0, os.path.join(TESTS, "..", "..", "..", "common"))


def matches(pattern, topic):
    return pattern == "*" or pattern == topic or (pattern.endswith(".*") and topic.startswith(pattern[:-1]))


class FakeBus:
    """bus.publish (kept, sent to subscribers), bus.emit (sent only), bus.get, subscribe with the current values."""

    def __init__(self):
        import websockets
        self.websockets = websockets
        self.values = {}
        self.clients = {}
        self.seen = []  # (topic, data) of everything published or emitted
        self.server = None

    async def start(self):
        self.server = await self.websockets.serve(self.handler, "127.0.0.1", 0)
        return "ws://127.0.0.1:%d" % self.server.sockets[0].getsockname()[1]

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()

    async def handler(self, ws):
        self.clients[ws] = set()
        try:
            async for raw in ws:
                message = json.loads(raw)
                if message["type"] == "subscribe":
                    self.clients[ws].update(message["topics"])
                    for topic, data in list(self.values.items()):
                        if any(matches(p, topic) for p in message["topics"]):
                            await ws.send(json.dumps({"type": "event", "topic": topic, "data": data}))
                elif message["type"] == "request":
                    params, result = message.get("params") or {}, {}
                    if message["method"] in ("bus.publish", "bus.emit"):
                        await self.send(params["topic"], params.get("data") or {},
                                        message["method"] == "bus.publish")
                    elif message["method"] == "bus.get":
                        result = self.values.get(params["topic"])
                    await ws.send(json.dumps({"type": "response", "id": message["id"], "result": result}))
        finally:
            del self.clients[ws]

    async def send(self, topic, data, keep=True):
        self.seen.append((topic, data))
        if keep:
            self.values[topic] = data
        for ws, patterns in list(self.clients.items()):
            if any(matches(p, topic) for p in patterns):
                try:
                    await ws.send(json.dumps({"type": "event", "topic": topic, "data": data}))
                except self.websockets.ConnectionClosed:
                    pass

    def subscribed(self, topic):
        return any(any(matches(p, topic) for p in patterns) for patterns in self.clients.values())


@unittest.skipUnless(importlib.util.find_spec("websockets"), "needs websockets")
class IntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import openhu
        import logger
        self.openhu, self.logger = openhu, logger
        self.dir = tempfile.TemporaryDirectory()
        self.bus = FakeBus()
        self.url = await self.bus.start()
        self.plugin, self.task = await self.start_plugin()
        self.next_id = 0

    async def asyncTearDown(self):
        await self.stop_plugin()
        await self.bus.stop()
        self.dir.cleanup()

    async def start_plugin(self):
        plugin = self.logger.LoggerPlugin(
            data_dir=self.dir.name, api=self.openhu.OpenHU(self.url),
            overrides={"enabled": True, "interval": 0.1, "rates": {"vehicle.*": 0.1}, "flushSeconds": 0.2,
                       "stopMinutes": 0.01,
                       "engineOffSeconds": 0.2},
            health=lambda data_dir: {"headunit.cpu_temp_c": 48})
        task = asyncio.create_task(plugin.main())
        await self.until(lambda: self.bus.subscribed("logger.query") and self.bus.subscribed("vehicle.speed"))
        return plugin, task

    async def stop_plugin(self):
        if self.task is not None:
            self.plugin.stop()
            await asyncio.wait_for(self.task, 5)
            self.task = None

    async def until(self, condition, timeout=5.0):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() > deadline:
                self.fail("timed out")
            await asyncio.sleep(0.02)

    async def ask(self, topic, **data):
        """Sends a query or command and waits for its logger.result."""
        self.next_id += 1
        request_id = "test:%d" % self.next_id
        await self.bus.send(topic, dict(data, id=request_id), keep=False)
        results = []

        def answered():
            results[:] = [d for t, d in self.bus.seen if t == "logger.result" and d.get("id") == request_id]
            return bool(results)
        await self.until(answered)
        return results[0]

    async def test_drive_query_and_clear(self):
        bus = self.bus
        await bus.send("signals.info", {"source": "test", "signals": {"vehicle.speed.kmh": {"unit": "km/h"}}})
        await bus.send("projection.state", {"connected": True})
        await bus.send("phone.status", {"callState": "in_call", "calls": [{"number": "+49123", "name": "Bob"}]})
        await bus.send("vehicle.gear", {"gear": "drive"})
        for kmh in (20, 40, 60, 60, 40):
            await bus.send("vehicle.speed", {"kmh": kmh})
            await asyncio.sleep(0.12)
        await bus.send("vehicle.speed", {"kmh": 0})
        # a trip starts and ends (standing still for 0.6 s)
        await self.until(lambda: any(t == "logger.trip" and d["event"] == "end" for t, d in bus.seen))
        start = [d for t, d in bus.seen if t == "logger.trip" and d["event"] == "start"]
        self.assertEqual(len(start), 1)

        result = await self.ask("logger.query", cmd="trips")
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["trips"]), 1)
        trip = result["trips"][0]
        self.assertEqual((trip["open"], trip["endReason"], trip["startReason"]), (False, "standstill", "speed"))
        self.assertGreater(trip["distance"], 0)
        self.assertEqual(trip["maxSpeed"], 60)
        self.assertGreater(trip["aaTime"], 0)

        await asyncio.sleep(0.3)  # the next batch is written
        result = await self.ask("logger.query", cmd="samples", trip=trip["id"], keys=["vehicle.speed.kmh"], points=0)
        values = result["series"]["vehicle.speed.kmh"]["v"]
        self.assertIn(60, values)
        self.assertEqual(values[-1], 0)
        result = await self.ask("logger.query", cmd="samples", trip=trip["id"], points=10)
        self.assertIn("headunit.cpu_temp_c", result["series"])
        self.assertLessEqual(len(result["series"]["vehicle.speed.kmh"]["t"]), 10)

        result = await self.ask("logger.query", cmd="events", start=0)
        self.assertEqual({(e["key"], e["value"]) for e in result["events"]},
                         {("vehicle.gear.gear", "drive"), ("phone.call_state", "in_call")})
        everything = await self.ask("logger.query", cmd="samples", start=0, points=0)
        self.assertNotIn("Bob", json.dumps(everything))
        self.assertNotIn("+49123", json.dumps(everything))
        signals = {s["name"]: s for s in (await self.ask("logger.query", cmd="signals"))["signals"]}
        self.assertEqual(signals["androidauto.connected"]["source"], "openhu:projection.state")
        self.assertEqual(signals["vehicle.speed.kmh"]["unit"], "km/h")  # from signals.info

        live = bus.values["logger.live"]
        self.assertEqual(live["values"]["vehicle.speed.kmh"], 0)
        self.assertEqual(live["values"]["phone.call_state"], "in_call")
        state = bus.values["logger.state"]
        self.assertTrue(state["vehicleData"])
        self.assertEqual(state["limitMB"], 1024)

        # wrong requests are answered with an error
        self.assertFalse((await self.ask("logger.query", cmd="nonsense"))["ok"])
        self.assertIn("start", (await self.ask("logger.query", cmd="samples"))["error"])
        self.assertFalse((await self.ask("logger.command", cmd="set", key="interval", value=999))["ok"])
        self.assertFalse((await self.ask("logger.command", cmd="set", key="rates.vehicle.*", value=0.01))["ok"])

        # delete all data
        self.assertTrue((await self.ask("logger.command", cmd="clear"))["ok"])
        self.assertEqual((await self.ask("logger.query", cmd="trips"))["trips"], [])
        self.assertEqual(bus.values["logger.state"]["usage"]["trips"], 0)

    async def test_settings_rates_and_recording(self):
        bus = self.bus
        self.assertTrue((await self.ask("logger.command", cmd="set", key="rates.vehicle.engine.*", value="update"))["ok"])
        self.assertTrue((await self.ask("logger.command", cmd="set", key="recording.triggers",
                                        value=[{"key": "vehicle.engine.rpm", "above": 3000}]))["ok"])
        self.assertTrue((await self.ask("logger.command", cmd="set", key="recording.postSeconds", value=0.3))["ok"])
        with open(os.path.join(self.dir.name, "config.json")) as file:
            saved = json.load(file)
        self.assertEqual(saved["rates"], {"vehicle.*": 0.1, "vehicle.engine.*": "update"})
        for rpm in [1000] * 5 + [3500] * 10 + [1500] * 5:
            await bus.send("vehicle.engine", {"rpm": rpm})
            await asyncio.sleep(0.02)
        await self.until(lambda: any(t == "logger.recording" and d["event"] == "end" for t, d in bus.seen))
        await asyncio.sleep(0.3)
        recordings = (await self.ask("logger.query", cmd="recordings"))["recordings"]
        self.assertEqual(len(recordings), 1)
        self.assertEqual(recordings[0]["reason"], "trigger")
        result = await self.ask("logger.query", cmd="samples", recording=recordings[0]["id"], points=0)
        self.assertIn(3500, result["series"]["vehicle.engine.rpm"]["v"])
        # every change in the log too ("update" rate)
        log = await self.ask("logger.query", cmd="samples", start=0, keys=["vehicle.engine.rpm"], points=0)
        self.assertEqual(log["series"]["vehicle.engine.rpm"]["v"], [1000, 3500, 1500])

        # by hand
        started = await self.ask("logger.command", cmd="record", action="start", label="test", seconds=30)
        self.assertTrue(started["ok"])
        self.assertFalse((await self.ask("logger.command", cmd="record", action="start"))["ok"])
        await bus.send("vehicle.engine", {"rpm": 2000})
        stopped = await self.ask("logger.command", cmd="record", action="stop")
        self.assertEqual(stopped["recording"]["id"], started["recording"]["id"])
        self.assertTrue((await self.ask("logger.command", cmd="deleteRecording", recording=recordings[0]["id"]))["ok"])
        self.assertEqual(len((await self.ask("logger.query", cmd="recordings"))["recordings"]), 1)

        # switched off: nothing more
        self.assertTrue((await self.ask("logger.command", cmd="set", key="enabled", value=False))["ok"])
        await bus.send("vehicle.engine", {"rpm": 2500})
        await asyncio.sleep(0.3)
        log = await self.ask("logger.query", cmd="samples", start=0, keys=["vehicle.engine.rpm"], points=0)
        self.assertNotIn(2500, log["series"]["vehicle.engine.rpm"]["v"])

    async def test_restart_resumes_trip(self):
        await self.bus.send("vehicle.speed", {"kmh": 50})
        await self.until(lambda: self.plugin.recorder.trip is not None)
        trip_id = self.plugin.recorder.trip["id"]
        await self.stop_plugin()  # SIGTERM while driving: the trip stays open
        self.plugin, self.task = await self.start_plugin()
        self.assertEqual(self.plugin.recorder.trip["id"], trip_id)
        result = await self.ask("logger.query", cmd="trip", trip=trip_id)
        self.assertTrue(result["trip"]["open"])


if __name__ == "__main__":
    unittest.main()
