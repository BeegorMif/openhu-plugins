// common/openhu.ts (bun test tests/ts): requests, events, Texts and the config store against a small fake OpenHU
// over a real WebSocket.
import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Config, OpenHU, OpenHUError, Texts, loadTs, matches, settingDefaults } from "../../common/openhu.ts";

const MANIFEST = {
  id: "org.test.p",
  settings: [
    { type: "section", key: "tuner" },
    { key: "rds", type: "switch", default: true },
    { key: "columns", type: "number", default: 4, min: 3, max: 6 },
  ],
};

let dir: string;
let pluginDir: string;
let dataDir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "openhu-ts-"));
  pluginDir = join(dir, "plugin");
  dataDir = join(dir, "data");
  mkdirSync(join(pluginDir, "i18n"), { recursive: true });
  mkdirSync(dataDir);
  writeFileSync(join(pluginDir, "manifest.json"), JSON.stringify(MANIFEST));
});

afterEach(() => rmSync(dir, { recursive: true, force: true }));

// OpenHU's side: plugin.config.*, bus.publish/subscribe, a method that fails
function fakeOpenHU(stored: Record<string, any> = {}, supported = true) {
  const requests: any[] = [];
  const values = () => ({ rds: true, columns: 4, ...stored });
  const subscribed = new Map<any, string[]>();
  const publish = (topic: string, data: any) => {
    for (const [ws, topics] of subscribed) {
      if (topics.some((pattern) => matches(pattern, topic))) {
        ws.send(JSON.stringify({ type: "event", topic, data }));
      }
    }
  };
  const server = Bun.serve({
    port: 0,
    fetch(request, server) {
      return server.upgrade(request) ? undefined : new Response("no", { status: 400 });
    },
    websocket: {
      message(ws, text) {
        const message = JSON.parse(String(text));
        if (message.type === "subscribe") {
          subscribed.set(ws, message.topics);
          return;
        }
        if (message.type !== "request") return;
        const { id, method, params } = message;
        requests.push({ method, params });
        const reply = (result: any) => ws.send(JSON.stringify({ type: "response", id, result }));
        const fail = (error: string) => ws.send(JSON.stringify({ type: "response", id, error }));
        if (!supported && method.startsWith("plugin.config.")) {
          fail("unknown method: " + method);
          return;
        }
        if (method === "plugin.config.set") {
          if ("columns" in params.values && ![3, 4, 5, 6].includes(params.values.columns)) {
            fail("columns: must be 3 to 6");
            return;
          }
          Object.assign(stored, params.values);
          const result: any = {};
          for (const key of Object.keys(params.values)) result[key] = (values() as any)[key];
          reply({ id: params.id, values: result });
          const event = { values: values(), changed: Object.keys(params.values) };
          setTimeout(() => publish("plugin.config." + params.id, event), 0);
        } else if (method === "plugin.config.remove") {
          for (const key of params.keys) delete stored[key];
          reply({ id: params.id, values: values() });
        } else if (method === "plugin.config.get") {
          reply({ id: params.id, values: values() });
        } else if (method === "bus.publish") {
          reply({});
          publish(params.topic, params.data);
        } else {
          fail("unknown method: " + method);
        }
      },
    },
  });
  return { server, requests, stored, publish, url: `ws://127.0.0.1:${server.port}` };
}

const until = async (condition: () => boolean, ms = 3000) => {
  const end = Date.now() + ms;
  while (!condition()) {
    if (Date.now() > end) throw new Error("timeout");
    await Bun.sleep(10);
  }
};

function client(url: string) {
  return new OpenHU({ url, pluginId: "org.test.p", dataDir, pluginDir });
}

test("matches like the shell", () => {
  expect(matches("*", "a.b")).toBe(true);
  expect(matches("nav.*", "nav.turn")).toBe(true);
  expect(matches("nav.*", "navi")).toBe(false);
  expect(matches("a.b", "a.b")).toBe(true);
});

test("texts from the .ts files", () => {
  const ts = (language: string, messages: string) =>
    writeFileSync(join(pluginDir, "i18n", language + ".ts"),
      `<?xml version="1.0" encoding="utf-8"?>\n<TS version="2.1" language="${language}"><context><name></name>${messages}</context></TS>`);
  const message = (id: string, text: string, type = "") =>
    `<message id="${id}"><source></source><translation${type ? ` type="${type}"` : ""}>${text}</translation></message>`;
  ts("en", message("x.hello", "Hello %1 &amp; %2") + message("x.todo", "", "unfinished") + message("x.old", "Old", "vanished"));
  ts("de", message("x.hello", "Hallo %1 &amp; %2"));
  expect(loadTs(join(pluginDir, "i18n", "en.ts")).size).toBe(1);
  const texts = new Texts(join(pluginDir, "i18n"), "en");
  expect(texts.tr("x.hello", "A", 2)).toBe("Hello A & 2");
  expect(texts.tr("x.old")).toBe("x.old");
  expect(texts.tr("x.hello", "A")).toBe("Hello A & %2");
  expect(texts.setLanguage("de")).toBe(true);
  expect(texts.tr("x.hello", "A", "B")).toBe("Hallo A & B");
  // no file: English
  texts.setLanguage("fr");
  expect(texts.tr("x.hello", 1, 2)).toBe("Hello 1 & 2");
});

test("config readable without a connection", () => {
  writeFileSync(join(dataDir, "config.json"), JSON.stringify({ stations: [101.3], columns: 5 }));
  expect(settingDefaults(pluginDir)).toEqual({ rds: true, columns: 4 });
  const api = client("ws://127.0.0.1:1");
  expect(api.config.get("rds")).toBe(true);
  expect(api.config.get("columns")).toBe(5);
  expect(api.config.get("stations")).toEqual([101.3]);
  expect(api.config.get("missing", 7)).toBe(7);
  expect(api.config.has("tuner")).toBe(false);
});

test("requests, events and config through OpenHU", async () => {
  const fake = fakeOpenHU({ columns: 6 });
  const api = client(fake.url);
  const events: any[] = [];
  const changes: any[] = [];
  api.on("speed.*", (topic, data) => events.push([topic, data]));
  api.onConfig((values, changed) => changes.push([values.columns, changed]));
  // changed before the connection: sent at the connect
  await api.config.set("stations", [99.5]);
  let connects = 0;
  const running = api.run(() => connects++);
  await until(() => connects === 1 && api.config.get("columns") === 6);
  expect(fake.stored.stations).toEqual([99.5]);
  // OpenHU's value taken at the connect, reported as a change from outside
  expect(changes).toEqual([[6, ["columns"]]]);

  await api.publish("speed.state", { kmh: 50 });
  await until(() => events.length === 1);
  expect(events[0]).toEqual(["speed.state", { kmh: 50 }]);

  expect(await api.config.set("columns", 5)).toBe(5);
  // the fake publishes its event a moment after the answer (sending it inside the handler breaks Bun's frames)
  await Bun.sleep(30);
  await expect(api.config.set("columns", 9)).rejects.toThrow(OpenHUError);
  await expect(api.request("no.such")).rejects.toThrow("unknown method");
  await api.config.remove("columns");
  expect(api.config.get("columns")).toBe(4);

  // changed in the settings by someone else
  fake.stored.rds = false;
  fake.publish("plugin.config.org.test.p", { values: { rds: false, columns: 4, stations: [99.5] }, changed: ["rds"] });
  await until(() => api.config.get("rds") === false);
  expect(changes.at(-1)).toEqual([4, ["rds"]]);
  // never written by the plugin itself
  expect(() => readFileSync(join(dataDir, "config.json"))).toThrow();

  api.stop();
  await running;
  fake.server.stop(true);
});

test("refused setting does not lose the other keys", async () => {
  const fake = fakeOpenHU();
  const api = client(fake.url);
  const running = api.run();
  await until(() => api.connected);
  api.config.queue({ columns: 9, stations: [1] }, []);
  await until(() => fake.stored.stations !== undefined);
  await until(() => api.config.get("columns") === 4);
  expect(fake.stored).toEqual({ stations: [1] });
  api.stop();
  await running;
  fake.server.stop(true);
});

test("OpenHU without a config store: the file", async () => {
  const fake = fakeOpenHU({}, false);
  const api = client(fake.url);
  const running = api.run();
  await until(() => api.connected);
  await api.config.set("stations", [1]);
  const file = JSON.parse(readFileSync(join(dataDir, "config.json"), "utf8"));
  expect(file).toEqual({ rds: true, columns: 4, stations: [1] });
  api.stop();
  await running;
  fake.server.stop(true);
});

test("Config is exported for plugins with their own client", () => {
  expect(typeof Config).toBe("function");
});
