#!/usr/bin/env python3
"""OpenHU instrument cluster.

Consumes decoded can.* topics from org.beegor.can and displays the
selected JSON display profile. Does not decode CAN frames or publish
vehicle.* topics.
"""

import asyncio
import json
import logging
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, HERE)

from openhu import DATA_DIR, PLUGIN_DIR, OpenHU, load_config, save_config, setup_logging

log = logging.getLogger("instrument-cluster")

DEFAULTS = {"profile": "car_brand"}


def profile_dirs():
    # User profiles override bundled profiles with the same filename.
    return [
        os.path.join(DATA_DIR, "profiles"),
        os.path.join(PLUGIN_DIR, "profiles"),
    ]


def list_profiles():
    names = set()

    for directory in profile_dirs():
        try:
            for filename in os.listdir(directory):
                if filename.endswith(".json"):
                    names.add(filename[:-5])
        except FileNotFoundError:
            log.warning("Profile directory does not exist: %s", directory)
        except OSError as error:
            log.warning("Cannot list profiles in %s: %s", directory, error)

    profiles = sorted(names)
    log.info("Cluster profile directories: %s", profile_dirs())
    log.info("Cluster available profiles: %s", profiles)
    return profiles


def load_profile(name):
    if not isinstance(name, str) or not name or os.path.basename(name) != name:
        raise ValueError("invalid profile name: %r" % name)

    for directory in profile_dirs():
        path = os.path.join(directory, name + ".json")
        if not os.path.isfile(path):
            continue

        with open(path, encoding="utf-8") as file:
            profile = json.load(file)

        if not isinstance(profile, dict):
            raise ValueError("profile must be a JSON object")

        items = profile.get("items")
        if not isinstance(items, list):
            raise ValueError("profile items must be an array")

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError("item %d must be an object" % index)
            for key in ("id", "topic", "field"):
                if not item.get(key):
                    raise ValueError("item %d missing %s" % (index, key))

        profile.setdefault("id", name)
        profile.setdefault("name", name)
        return profile

    raise FileNotFoundError("profile %s not found" % name)


class ClusterPlugin:
    def __init__(self):
        self.config = load_config(DEFAULTS)
        self.api = OpenHU()
        self.profile = None
        self.profile_error = ""

        # Latest decoded payload for every CAN topic.
        self.can_values = {}

        self.api.on("can.*", self.on_can_data)
        self.api.on("cluster.command", self.on_command)

        self.load_profile()

    async def publish_state(self):
        profiles = list_profiles()
        profile = self.profile

        await self.api.safe(
            self.api.publish(
                "cluster.state",
                profile=self.config.get("profile", ""),
                profileName=profile["name"] if profile else "",
                profiles=profiles,
                items=profile["items"] if profile else [],
                error=self.profile_error,
            )
        )

        for topic, payload in list(self.can_values.items()):
            await self.api.safe(
                self.api.publish(
                    "cluster.data",
                    sourceTopic=topic,
                    data=payload,
                )
            )

    def load_profile(self):
        try:
            self.profile = load_profile(self.config["profile"])
            self.profile_error = ""
            log.info(
                "Loaded display profile %s (%d items)",
                self.config["profile"],
                len(self.profile["items"]),
            )
        except (OSError, ValueError, KeyError) as error:
            self.profile = None
            self.profile_error = str(error)
            log.exception("Cannot load display profile")


    async def on_connect(self):
        log.info("Cluster connected; publishing display state")
        await self.publish_state()


    async def on_can_data(self, topic, data):
        """Cache and forward every decoded CAN event."""
        payload = data if isinstance(data, dict) else {}
        self.can_values[topic] = payload

        await self.api.safe(
            self.api.publish(
                "cluster.data",
                sourceTopic=topic,
                data=payload,
            )
        )

    async def on_command(self, topic, data):
        command = data.get("cmd")
        value = data.get("value")

        if command == "profile":
            if not isinstance(value, str) or value not in list_profiles():
                log.warning("Unknown display profile: %r", value)
                return

            previous = self.config.get("profile")
            self.config["profile"] = value
            self.load_profile()

            if self.profile is None:
                self.config["profile"] = previous
                self.load_profile()
            else:
                save_config(self.config)

            await self.publish_state()

        elif command == "reload":
            self.load_profile()
            await self.publish_state()

        else:
            log.warning("Unknown cluster command: %s", command)

    async def main(self):
        await self.api.run(self.on_connect)


if __name__ == "__main__":
    setup_logging()
    asyncio.run(ClusterPlugin().main())
