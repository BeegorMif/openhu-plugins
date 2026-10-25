#!/usr/bin/env python3
"""Set monitor brightness and power the display off after the CAN ignition turns off."""

import asyncio
import logging
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
log = logging.getLogger("display")
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

from openhu import PLUGIN_ID, OpenHU, load_config, save_config, setup_logging  # noqa: E402

DEFAULTS = {"topic": "can.display", "field": "dimByte", "display": "", "enabled": True,
            "extraDim": False, "ignitionTopic": "can.ignition", "ignitionPowerOff": False,
            "ignitionDelaySeconds": 300, "ignitionEverOn": False, "shutdownDeadline": 0, "autoExtraDim": False, "autoExtraDimBelow": 10, "extraDimLightsOff": False,
            "lightsTopic": "", "lightsField": "", "brightnessTopic": "can.dashboard", "brightnessField": "brightnessRaw" }

# Prevent automatic extra dim from flickering around the configured threshold.
AUTO_DIM_HYSTERESIS = 2


class DisplayPlugin:
    def __init__(self, api=None, config=None):
        self.config = {**DEFAULTS, **(config if config is not None else load_config(DEFAULTS))}
        self.api = api or OpenHU()
        self.last_signal = None
        self.error = ""
        self.ignition_state = "UNKNOWN"
        self.ignition_blackout = False
        self.overlay_synced = False
        self.shutdown_task = None
        self.shutdown_deadline = float(self.config.get("shutdownDeadline", 0) or 0)
        self.lights_state = "UNKNOWN"
        self.brightness_state = "UNKNOWN"
        self.auto_dim_active = False
        self.auto_dim_suppressed = False
        self.api.on("can.*", self.on_can)
        self.api.on("display.command", self.on_command)

    async def ddc(self, *args):
        command = ["ddcutil", "--display", "1", *map(str, args)]
        try:
            result = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError:
            raise RuntimeError("ddcutil is not installed")
        stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=12)
        if result.returncode:
            detail = (stderr or stdout).decode(errors="replace").strip()
            raise RuntimeError(detail or "ddcutil exited with status %d" % result.returncode)
        return stdout.decode(errors="replace")

    def update_auto_dim(self):
        """Update automatic extra dim using the current brightness."""
        if not self.config.get("autoExtraDim") or self.last_signal is None:
            self.auto_dim_active = False
            self.auto_dim_suppressed = False
            return

        below = int(self.config.get("autoExtraDimBelow", 10))

        if self.last_signal >= below + AUTO_DIM_HYSTERESIS:
            self.auto_dim_active = False
            self.auto_dim_suppressed = False
        elif self.last_signal < below and not self.auto_dim_suppressed:
            self.auto_dim_active = True

    def effective_extra_dim(self):
        """Lights-off configuration takes priority over extra dim."""
        if (self.config.get("extraDimLightsOff") and self.lights_state == "OFF"):
            return False

        return bool(self.config["extraDim"]) or self.auto_dim_active

    async def publish(self):
        self.update_auto_dim()
        extra_dim = self.effective_extra_dim()

        await self.api.publish(
            "display.state",
            canTopic=self.config["topic"],
            field=self.config["field"],
            brightnessTopic=self.config["brightnessTopic"],
            brightnessField=self.config["brightnessField"],
            brightnessState=self.brightness_state,
            enabled=self.config["enabled"],
            display=self.config["display"],
            lastSignal=self.last_signal,
            extraDim=extra_dim,
            error=self.error,
            extraDimAuto=self.auto_dim_active and extra_dim,
            autoExtraDim=self.config["autoExtraDim"],
            autoExtraDimBelow=self.config["autoExtraDimBelow"],
            extraDimLightsOff=self.config["extraDimLightsOff"],
            lightsTopic=self.config["lightsTopic"],
            lightsField=self.config["lightsField"],
            lightsState=self.lights_state,
            ignitionTopic=self.config["ignitionTopic"],
            ignitionPowerOff=self.config["ignitionPowerOff"],
            ignitionDelaySeconds=self.config["ignitionDelaySeconds"],
            ignitionState=self.ignition_state,
            ignitionBlackout=self.ignition_blackout,
            shutdownPending=self.shutdown_deadline > 0,
            shutdownInSeconds=(
                max(0, round(self.shutdown_deadline - time.time()))
                if self.shutdown_deadline
                else 0
            ),
        )

        await self.api.publish("ui.extraDim", enabled=extra_dim, source=PLUGIN_ID)

    async def set_ignition_blackout(self, enabled):
        enabled = bool(enabled)
        if self.ignition_blackout == enabled and self.overlay_synced:
            return
        self.ignition_blackout = enabled
        method = "ui.overlay.show" if enabled else "ui.overlay.hide"

        result = await self.api.safe(
            self.api.request(method, id=PLUGIN_ID)
        )
        self.overlay_synced = result is not None
        await self.publish()

    def cancel_shutdown(self):
        task, self.shutdown_task = self.shutdown_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self.shutdown_deadline = 0
        self.config["shutdownDeadline"] = 0
        save_config(self.config)

    async def ignition_changed(self, data):
        # The CAN profile publishes both ignition bits together on can.ignition. Ignore the
        # CAN plugin's available:false marker: a silent bus is not proof of OFF.
        if not isinstance(data, dict) or data.get("available") is False:
            return
        if "terminalR" not in data or "terminal15" not in data:
            return

        active = bool(data["terminalR"]) or bool(data["terminal15"])
        self.ignition_state = "ON" if active else "OFF"
        if active:
            if not self.config.get("ignitionEverOn"):
                self.config["ignitionEverOn"] = True
                save_config(self.config)
            self.cancel_shutdown()
            await self.set_ignition_blackout(False)
            await self.publish()
            return

        if not self.config.get("ignitionPowerOff") or not self.config.get("ignitionEverOn"):
            await self.publish()
            return

        # Keep an absolute deadline in plugin config so a plugin restart does not
        # silently discard an ignition-off shutdown already in progress.
        if self.shutdown_deadline <= 0:
            delay = max(1, min(86400, int(self.config.get("ignitionDelaySeconds", 300))))
            self.shutdown_deadline = time.time() + delay
            self.config["shutdownDeadline"] = self.shutdown_deadline
            save_config(self.config)
        await self.set_ignition_blackout(True)
        if self.shutdown_task is None or self.shutdown_task.done():
            self.shutdown_task = asyncio.create_task(self.power_off_when_due(self.shutdown_deadline))
        await self.publish()

    async def lights_changed(self, data):
        """Update lights state from a boolean or numeric CAN field."""
        field = self.config.get("lightsField")

        if (not isinstance(data, dict) or data.get("available") is False or field not in data):
            return

        value = data[field]

        if isinstance(value, bool):
            on = value
        elif isinstance(value, (int, float)):
            on = value != 0
        else:
            return

        state = "ON" if on else "OFF"

        if state != self.lights_state:
            self.lights_state = state
            await self.publish()

    async def brightness_changed(self, data):
        """Update CAN brightness state and automatic extra dim."""
        if not isinstance(data, dict) or data.get("available") is False:
            return

        field = self.config.get("brightnessField")
        value = data.get(field)

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return

        dim_byte = max(0, min(255, value))
        brightness = round(dim_byte / 255 * 100)

        # Update the CAN-derived state first, independently of ddcutil.
        self.brightness_state = brightness
        self.last_signal = brightness
        self.error = ""

        await self.publish()

        # Apply monitor brightness separately; failure must not prevent auto-dim.
        try:
            await self.ddc("setvcp", "10", str(brightness))
        except (OSError, RuntimeError, TypeError, ValueError, asyncio.TimeoutError) as error:
            self.error = str(error)
            await self.publish()

    async def power_off_when_due(self, deadline):
        try:
            while self.shutdown_deadline == deadline:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(1, remaining))

                if (self.ignition_state != "OFF" or not self.config.get("ignitionPowerOff")
                ):
                    return
                await self.publish()

            if (
                self.shutdown_deadline != deadline
                or self.ignition_state != "OFF"
                or not self.config.get("ignitionPowerOff")
            ):
                return
            await self.request_poweroff()
            self.shutdown_deadline = 0
            self.config["shutdownDeadline"] = 0
            save_config(self.config)
        except asyncio.CancelledError:
            raise
        except (OSError, RuntimeError, asyncio.TimeoutError) as error:
            self.error = "Power off failed: %s" % error
            await self.publish()
            log.error("%s", self.error)
        finally:
            if self.shutdown_task is asyncio.current_task():
                self.shutdown_task = None

    async def request_poweroff(self):
        process = await asyncio.create_subprocess_exec(
            "systemctl", "poweroff", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        if process.returncode:
            detail = (stderr or stdout).decode(errors="replace").strip()
            raise RuntimeError(detail or "systemctl poweroff exited with status %d" % process.returncode)

    async def set_brightness(self, value):
        value = max(0, min(100, round(float(value))))
        if self.last_signal == value:
            return
        await self.ddc("setvcp", "10", str(value))
        self.last_signal = value
        self.error = ""
        await self.publish()

    async def on_can(self, topic, data):
        if topic == self.config.get("ignitionTopic"):
            await self.ignition_changed(data)
        if (self.config.get("lightsTopic") and topic == self.config.get("lightsTopic")):
            await self.lights_changed(data)
        if (self.config.get("brightnessTopic") and topic == self.config.get("brightnessTopic")):
            await self.brightness_changed(data)

        if not self.config.get("enabled") or topic != self.config.get("topic"):
            return

        if not isinstance(data, dict) or data.get("available") is False:
            return

        value = data.get(self.config.get("field"))

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return

    async def on_command(self, topic, data):
        command = data.get("cmd")
        try:
            if command == "configure":
                can_topic = str(data.get("topic", "")).strip()
                field = str(data.get("field", "")).strip()
                display = str(data.get("display", "")).strip()
                if not re.fullmatch(r"can\.[A-Za-z0-9_.-]+", can_topic):
                    raise ValueError("Topic must be a CAN topic, for example can.display")
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", field):
                    raise ValueError("Signal field is required")
                if display and not display.isdigit():
                    raise ValueError("Display must be a numeric ddcutil display number")
                self.config.update(topic=can_topic, field=field, display=display,
                                   enabled=bool(data.get("enabled", True)))
                save_config(self.config)
                current = await self.api.request("bus.get", topic=can_topic)
                await self.on_can(can_topic, current)
            elif command == "configureBrightness":
                brightness_topic = str(data.get("brightnessTopic", "")).strip()
                brightness_field = str(data.get("brightnessField", "")).strip()
                if not re.fullmatch(r"can\.[A-Za-z0-9_.-]+", brightness_topic):
                    raise ValueError("Brightness topic must be a CAN topic, ""for example can.dashboard")

                if not re.fullmatch(r"[A-Za-z0-9_.-]+", brightness_field):
                    raise ValueError("Brightness field is required")

                self.config.update(brightnessTopic=brightness_topic,brightnessField=brightness_field)
                save_config(self.config)

                current = await self.api.request("bus.get", topic=brightness_topic)
                await self.on_can(brightness_topic, current)

            elif command == "extraDim":
                self.config["extraDim"] = bool(data.get("enabled", False))
                if self.config["extraDim"]:
                    self.auto_dim_suppressed = False
                elif self.auto_dim_active:
                    self.auto_dim_active = False
                    self.auto_dim_suppressed = True
                save_config(self.config)
            elif command == "autoExtraDim":
                below = int(data.get("below", 10))
                if not 1 <= below <= 100:
                    raise ValueError("Auto extra dim level must be 1–100 %")
                self.config["autoExtraDim"] = bool(data.get("enabled", False))
                self.config["autoExtraDimBelow"] = below
                self.auto_dim_suppressed = False
                save_config(self.config)
            elif command == "extraDimLightsOff":
                self.config["extraDimLightsOff"] = bool(data.get("enabled", False))
                save_config(self.config)
            elif command == "ignitionPowerOff":
                delay_minutes = int(data.get("delayMinutes", 5))
                if not 1 <= delay_minutes <= 120:
                    raise ValueError("Ignition power-off delay must be 1–120 minutes")
                self.config["ignitionPowerOff"] = bool(data.get("enabled", False))
                self.config["ignitionDelaySeconds"] = delay_minutes * 60
                save_config(self.config)
                if not self.config["ignitionPowerOff"]:
                    self.cancel_shutdown()
                    await self.set_ignition_blackout(False)
                elif self.ignition_state == "OFF" and self.config.get("ignitionEverOn"):
                    await self.ignition_changed({"terminalR": False, "terminal15": False})
            elif command == "manual":
                await self.set_brightness(data.get("value", 0))
            else:
                return
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self.error = str(error)
        await self.publish()

    async def run(self):
        await self.api.run(self.on_connect)

    async def on_connect(self):
        """Apply the current CAN values too, if it was published before this plugin connected."""
        try:
            await self.publish()
            # Reconcile any stale shell overlay before restoring ignition state.
            await self.set_ignition_blackout(False)
            brightness_topic = self.config.get("brightnessTopic")
            legacy_topic = self.config.get("topic")
            ignition_topic = self.config.get("ignitionTopic")
            lights_topic = self.config.get("lightsTopic")

            # Use the configured brightness topic if it is separate.
            if brightness_topic and brightness_topic != legacy_topic:
                data = await self.api.request("bus.get", topic=brightness_topic)
                await self.on_can(brightness_topic, data)
            else:
                data = await self.api.request("bus.get", topic=legacy_topic)
                await self.on_can(legacy_topic, data)

            ignition = await self.api.request("bus.get", topic=ignition_topic)
            await self.on_can(ignition_topic, ignition)

            if (lights_topic and lights_topic not in (legacy_topic, ignition_topic, brightness_topic)):
                lights = await self.api.request("bus.get", topic=lights_topic)
                await self.on_can(lights_topic, lights)

        except Exception as error:
            self.error = str(error)
            await self.publish()


if __name__ == "__main__":
    setup_logging()
    asyncio.run(DisplayPlugin().run())
