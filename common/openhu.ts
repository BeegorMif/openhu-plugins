/**
 * Small client for the OpenHU API for plugin processes in TypeScript, run with bun (the same as openhu.py).
 *
 *   const api = new OpenHU();
 *   api.on("vehicle.*", (topic, data) => ...);           // events (sync or async callbacks)
 *   await api.request("volume.set", { value: 40 });     // methods, throws OpenHUError
 *   await api.publish("vehicle.speed", { kmh: 50 });    // state other plugins/the shell can read
 *   await api.emit("radio.command", { cmd: "tune" });   // one-shot event
 *   await api.action("media.next");                     // same as a steering wheel button
 *   await api.run(onConnect);                           // connects and reconnects forever
 *
 *   const texts = new Texts();                          // texts of the process in the shell's language
 *   texts.follow(api, onChange);                        // ...also after a switch
 *   texts.tr("org.example.speed.error.no_sensor");      // i18n/<language>.ts, like qsTrId() in QML
 *
 *   api.config.get("ppm");                              // the plugin's config store in OpenHU (openhu#152), at once:
 *   api.config.get("stations", []);                     // manifest defaults + config.json, no connection needed
 *   await api.config.set("frequency", 101.3);           // through OpenHU (checks declared settings); offline: later
 *   await api.config.update({ band: "fm" });            // several keys, all or none
 *   await api.config.remove("oldKey");                  // free key deleted, a setting back to its default
 *   api.onConfig((values, changed) => ...);             // changed in Settings → Apps or by another client
 *
 * Environment (set by OpenHU): OPENHU_API_URL, OPENHU_PLUGIN_ID, OPENHU_PLUGIN_DIR, OPENHU_DATA_DIR, OPENHU_LANGUAGE,
 * OPENHU_PLUGIN_TOKEN (the process logs in with it, so its values count as the plugin's: only plugins that declare
 * "androidAuto" in their manifest feed Android Auto, openhu#123).
 * OPENHU_API_TOKEN (optional, not set by OpenHU): API token, only needed from another computer, e.g. while developing
 * a plugin against a head unit (OPENHU_API_URL=ws://<head unit>:5520). On the head unit itself no token is needed.
 *
 * bun is not part of OpenHU OS: a plugin written with this runs where bun is installed.
 */

import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { homedir } from "node:os";

export type Data = Record<string, any>;
export type Callback = (topic: string, data: Data) => unknown;
export type ConfigCallback = (values: Data, changed: string[]) => unknown;

const env = process.env;
export const PLUGIN_ID = env.OPENHU_PLUGIN_ID || "plugin";
// lib/openhu.ts in the plugin archive: the plugin is the folder above
export const PLUGIN_DIR = env.OPENHU_PLUGIN_DIR || resolve(import.meta.dir, "..");
export const DATA_DIR = env.OPENHU_DATA_DIR || join(homedir(), ".openhu", "plugin-data", PLUGIN_ID);

export class OpenHUError extends Error {}

const log = {
  info: (...args: unknown[]) => console.log(new Date().toISOString(), "INFO openhu:", ...args),
  warning: (...args: unknown[]) => console.warn(new Date().toISOString(), "WARNING openhu:", ...args),
};

/** Same rules as the shell: "*", "nav.*" or an exact topic. */
export function matches(pattern: string, topic: string): boolean {
  return pattern === "*" || pattern === topic || (pattern.endsWith(".*") && topic.startsWith(pattern.slice(0, -1)));
}

export function readJson(path: string): Data {
  try {
    const data = JSON.parse(readFileSync(path, "utf8"));
    return data && typeof data === "object" && !Array.isArray(data) ? data : {};
  } catch {
    return {};
  }
}

export function writeJson(path: string, data: Data): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path + ".tmp", JSON.stringify(data, null, 2));
  renameSync(path + ".tmp", path);
}

/** key -> default of the settings declared in manifest.json (without sections). */
export function settingDefaults(pluginDir: string = PLUGIN_DIR): Data {
  const settings = readJson(join(pluginDir, "manifest.json")).settings;
  const defaults: Data = {};
  if (Array.isArray(settings)) {
    for (const entry of settings) {
      if (entry && typeof entry === "object" && entry.type !== "section" && "key" in entry && "default" in entry) {
        defaults[entry.key] = entry.default;
      }
    }
  }
  return defaults;
}

const clone = <T>(value: T): T => (value === undefined ? value : JSON.parse(JSON.stringify(value)));
const same = (a: unknown, b: unknown): boolean => JSON.stringify(a) === JSON.stringify(b);

// ---------------------------------------------------------------------------------------------------- texts

function decodeXml(text: string): string {
  return text
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&#(x?)([0-9a-fA-F]+);/g, (_, hex, code) => String.fromCodePoint(parseInt(code, hex ? 16 : 10)))
    .replace(/&amp;/g, "&");
}

/** Text ID -> translation of a Qt .ts file (lrelease -idbased); untranslated and removed entries are left out. */
export function loadTs(path: string): Map<string, string> {
  const texts = new Map<string, string>();
  let xml: string;
  try {
    xml = readFileSync(path, "utf8");
  } catch {
    return texts;
  }
  const message = /<message\b[^>]*\bid="([^"]*)"[^>]*>([\s\S]*?)<\/message>/g;
  for (const [, id, body] of xml.matchAll(message)) {
    const translation = /<translation\b([^>]*?)(?:\/>|>([\s\S]*?)<\/translation>)/.exec(body);
    if (!translation || !translation[2]) continue;
    const type = /\btype="([^"]*)"/.exec(translation[1] || "");
    if (type && ["unfinished", "vanished", "obsolete"].includes(type[1])) continue;
    texts.set(decodeXml(id), decodeXml(translation[2]));
  }
  return texts;
}

/**
 * Texts of a plugin process in the language of the shell. They live in the same files as the texts of the plugin's
 * QML, i18n/<language>.ts (IDs "<plugin id>.<area>.<key>"), arguments are %1, %2, ... like qsTrId(...).arg(...). An
 * ID without a translation comes back as the ID, like in QML; a language without a file falls back to English.
 */
export class Texts {
  directory: string;
  language: string | null = null;
  texts = new Map<string, string>();

  constructor(directory?: string, language?: string) {
    this.directory = directory || join(PLUGIN_DIR, "i18n");
    this.setLanguage(language || env.OPENHU_LANGUAGE || "en");
  }

  /** Loads the texts of a language; true if it changed. */
  setLanguage(language: string): boolean {
    if (language === this.language) return false;
    this.language = language;
    const path = join(this.directory, language + ".ts");
    this.texts = loadTs(existsSync(path) ? path : join(this.directory, "en.ts"));
    return true;
  }

  tr(id: string, ...args: unknown[]): string {
    const text = this.texts.get(id) ?? id;
    return text.replace(/%(\d+)/g, (match, n) => {
      const index = Number(n);
      return index > 0 && index <= args.length ? String(args[index - 1]) : match;
    });
  }

  /** Follows a language switch of the shell (topic ui.language), then calls onChange(). Call before api.run(). */
  follow(api: OpenHU, onChange?: () => unknown): void {
    api.on("ui.language", async (_topic, data) => {
      if (this.setLanguage(data.language || "en") && onChange) await onChange();
    });
  }
}

// ---------------------------------------------------------------------------------------------------- config

const REMOVED = Symbol("removed");

/**
 * The plugin's config store in OpenHU (openhu#152, openhu/docs/plugins.md#config-store): one JSON object, declared
 * keys are the settings of manifest.json (shown in Settings → Apps, checked by OpenHU), all other keys are free.
 *
 * Readable at once (the manifest's defaults and config.json, no connection needed) and kept current from the topic
 * plugin.config.<id>. Changes go through OpenHU; made while not connected, they apply locally and are sent once the
 * connection is there. Against an OpenHU without the store, config.json is written directly.
 */
export class Config {
  readonly pluginId: string;
  readonly dataDir: string;
  readonly pluginDir: string;
  readonly defaults: Data;
  private values: Data;
  private pending = new Map<string, unknown>();
  private callbacks: ConfigCallback[] = [];
  private supported: boolean | null = null;

  constructor(private api: OpenHU, pluginId?: string, dataDir?: string, pluginDir?: string) {
    this.pluginId = pluginId || PLUGIN_ID;
    this.dataDir = dataDir || DATA_DIR;
    this.pluginDir = pluginDir || PLUGIN_DIR;
    this.defaults = settingDefaults(this.pluginDir);
    this.values = { ...clone(this.defaults), ...readJson(join(this.dataDir, "config.json")) };
  }

  get topic(): string {
    return "plugin.config." + this.pluginId;
  }

  get(key: string): any;
  get<T>(key: string, fallback: T): T;
  get(key: string, fallback?: unknown): any {
    return key in this.values ? this.values[key] : fallback;
  }

  has(key: string): boolean {
    return key in this.values;
  }

  keys(): string[] {
    return Object.keys(this.values);
  }

  asObject(): Data {
    return { ...this.values };
  }

  /** callback(values, changed) when values change from outside: Settings → Apps, another client, the file by hand. */
  onChange(callback: ConfigCallback): void {
    this.callbacks.push(callback);
  }

  /** Sets one key; returns the value as stored. Throws OpenHUError for a value a declared setting does not take. */
  async set(key: string, value: unknown): Promise<any> {
    return (await this.update({ [key]: value }))[key];
  }

  /** Sets several keys, all or none; returns them as stored. */
  async update(changes: Data): Promise<Data> {
    changes = clone(changes);
    if (this.api.connected && this.supported !== false) {
      try {
        const result = await this.api.request("plugin.config.set", { id: this.pluginId, values: changes });
        Object.assign(this.values, result.values || {});
        return result.values || {};
      } catch (error) {
        if (!String(error).includes("unknown method")) throw error;
        this.supported = false;
      }
    }
    this.queue(changes, []);
    return changes;
  }

  /** A free key is deleted, a declared setting goes back to its default. */
  async remove(...keys: string[]): Promise<void> {
    if (this.api.connected && this.supported !== false) {
      try {
        const result = await this.api.request("plugin.config.remove", { id: this.pluginId, keys });
        this.values = result.values || this.values;
        return;
      } catch (error) {
        if (!String(error).includes("unknown method")) throw error;
        this.supported = false;
      }
    }
    this.queue({}, keys);
  }

  /** Applies changes locally and sends them when possible. */
  queue(changes: Data, removed: string[]): void {
    for (const [key, value] of Object.entries(changes)) {
      this.values[key] = clone(value);
      this.pending.set(key, clone(value));
    }
    for (const key of removed) {
      delete this.values[key];
      if (key in this.defaults) this.values[key] = clone(this.defaults[key]);
      this.pending.set(key, REMOVED);
    }
    if (this.supported === false) {
      this.writeFile();
    } else if (this.api.connected) {
      void this.flush();
    }
  }

  /** Sends the queued changes (also called on every connect). */
  async flush(): Promise<void> {
    if (this.pending.size === 0 || !this.api.connected) return;
    const pending = this.pending;
    this.pending = new Map();
    const changes: Data = {};
    const removed: string[] = [];
    for (const [key, value] of pending) {
      if (value === REMOVED) removed.push(key);
      else changes[key] = value;
    }
    try {
      if (this.supported !== false) {
        if (Object.keys(changes).length) {
          await this.api.request("plugin.config.set", { id: this.pluginId, values: changes });
        }
        if (removed.length) await this.api.request("plugin.config.remove", { id: this.pluginId, keys: removed });
        return;
      }
    } catch (error) {
      const text = String(error);
      if (text.includes("unknown method")) {
        this.supported = false;
      } else if (text.includes("connection lost") || text.includes("not connected")) {
        for (const [key, value] of pending) if (!this.pending.has(key)) this.pending.set(key, value);
        return;
      } else {
        // refused: key by key, so the other keys are not lost with it; OpenHU keeps its value for the refused one
        for (const [key, value] of Object.entries(changes)) {
          try {
            await this.api.request("plugin.config.set", { id: this.pluginId, values: { [key]: value } });
          } catch (refused) {
            log.warning("config:", String(refused));
          }
        }
        if (removed.length) {
          await this.api.safe(this.api.request("plugin.config.remove", { id: this.pluginId, keys: removed }));
        }
        await this.sync();
        return;
      }
    }
    this.writeFile();
  }

  /** @internal on every connect: send what is queued, then take OpenHU's values */
  async connected(): Promise<void> {
    await this.flush();
    await this.sync();
  }

  private async sync(): Promise<void> {
    if (this.supported === false) return;
    try {
      const result = await this.api.request("plugin.config.get", { id: this.pluginId });
      await this.take(result.values || {});
    } catch (error) {
      if (String(error).includes("unknown method")) {
        this.supported = false;
        this.writeFile();
      }
    }
  }

  /** @internal the topic plugin.config.<id> */
  async onTopic(_topic: string, data: Data): Promise<void> {
    // local changes still to be sent win until they are
    if (this.pending.size === 0 && data.values && typeof data.values === "object") await this.take(data.values);
  }

  private async take(values: Data): Promise<void> {
    const keys = new Set([...Object.keys(values), ...Object.keys(this.values)]);
    const changed = [...keys].filter((key) => !same(values[key], this.values[key]) || (key in values) !== (key in this.values)).sort();
    this.values = { ...values };
    if (changed.length === 0) return;
    for (const callback of [...this.callbacks]) {
      try {
        await callback({ ...values }, changed);
      } catch (error) {
        log.warning("config callback failed:", error);
      }
    }
  }

  private writeFile(): void {
    // OpenHU without a config store: the file as before
    writeJson(join(this.dataDir, "config.json"), this.values);
  }
}

// ---------------------------------------------------------------------------------------------------- API

export interface OpenHUOptions {
  url?: string;
  token?: string;
  pluginId?: string;
  dataDir?: string;
  pluginDir?: string;
}

export class OpenHU {
  readonly url: string;
  readonly token: string | undefined;
  readonly pluginToken: string | undefined;
  readonly config: Config;
  private ws: WebSocket | null = null;
  private nextId = 0;
  private pending = new Map<number, (message: Data) => void>();
  private handlers: [string, Callback][] = [];

  constructor(options: OpenHUOptions = {}) {
    this.url = options.url || env.OPENHU_API_URL || "ws://127.0.0.1:5520";
    this.token = options.token || env.OPENHU_API_TOKEN;
    this.pluginToken = env.OPENHU_PLUGIN_TOKEN;
    this.config = new Config(this, options.pluginId, options.dataDir, options.pluginDir);
    this.on(this.config.topic, (topic, data) => this.config.onTopic(topic, data));
  }

  get connected(): boolean {
    return this.ws !== null;
  }

  on(pattern: string, callback: Callback): void {
    this.handlers.push([pattern, callback]);
  }

  /** callback(values, changed) when the config store changes from outside (see Config.onChange). */
  onConfig(callback: ConfigCallback): void {
    this.config.onChange(callback);
  }

  async request(method: string, params: Data = {}): Promise<any> {
    const ws = this.ws;
    if (!ws) throw new OpenHUError("not connected");
    const id = ++this.nextId;
    const response = await new Promise<Data>((resolveResponse, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new OpenHUError(method + ": timeout"));
      }, 10000);
      this.pending.set(id, (message) => {
        clearTimeout(timer);
        resolveResponse(message);
      });
      ws.send(JSON.stringify({ type: "request", id, method, params }));
    });
    if ("error" in response) throw new OpenHUError(`${method}: ${response.error}`);
    return response.result;
  }

  publish(topic: string, data: Data = {}): Promise<any> {
    return this.request("bus.publish", { topic, data });
  }

  emit(topic: string, data: Data = {}): Promise<any> {
    return this.request("bus.emit", { topic, data });
  }

  action(name: string, phase = "click"): Promise<any> {
    return this.request("input.action", { action: name, phase });
  }

  /** Awaits a request, logs instead of throwing (e.g. while OpenHU restarts). */
  async safe<T>(promise: Promise<T>): Promise<T | null> {
    try {
      return await promise;
    } catch (error) {
      log.warning(String(error));
      return null;
    }
  }

  /** Connects and reconnects forever. stop() (for tests) ends it. */
  async run(onConnect?: () => unknown): Promise<void> {
    this.stopped = false;
    while (!this.stopped) {
      await this.connectOnce(onConnect);
      if (!this.stopped) await new Promise((r) => setTimeout(r, 2000));
    }
  }

  private stopped = false;

  stop(): void {
    this.stopped = true;
    this.ws?.close();
  }

  private connectOnce(onConnect?: () => unknown): Promise<void> {
    return new Promise((done) => {
      let ws: WebSocket;
      try {
        ws = new WebSocket(this.url);
      } catch (error) {
        log.info(`API not reachable (${error}), retrying`);
        done();
        return;
      }
      ws.onopen = () => {
        this.ws = ws;
        log.info("connected to", this.url);
        // answered with {"type":"auth"}; messages are handled in order, so no need to wait for it
        if (this.pluginToken) ws.send(JSON.stringify({ type: "auth", pluginToken: this.pluginToken }));
        else if (this.token) ws.send(JSON.stringify({ type: "auth", token: this.token }));
        const topics = [...new Set(this.handlers.map(([pattern]) => pattern))].sort();
        if (topics.length) ws.send(JSON.stringify({ type: "subscribe", topics }));
        void OpenHU.call(() => this.config.connected());
        if (onConnect) void OpenHU.call(onConnect);
      };
      ws.onmessage = (event) => this.dispatch(JSON.parse(String(event.data)));
      ws.onerror = () => {};
      ws.onclose = () => {
        if (this.ws === ws) this.ws = null;
        for (const resolvePending of this.pending.values()) resolvePending({ error: "connection lost" });
        this.pending.clear();
        if (!this.stopped) log.info("API not reachable, retrying");
        done();
      };
    });
  }

  private dispatch(message: Data): void {
    if (message.type === "response") {
      const resolvePending = this.pending.get(message.id);
      if (resolvePending) {
        this.pending.delete(message.id);
        resolvePending(message);
      }
    } else if (message.type === "event") {
      const topic = message.topic || "";
      const data = message.data || {};
      for (const [pattern, callback] of this.handlers) {
        if (matches(pattern, topic)) void OpenHU.call(() => callback(topic, data));
      }
    } else if (message.type === "error") {
      log.warning("API:", message.error);
    }
  }

  private static async call(callback: () => unknown): Promise<void> {
    try {
      await callback();
    } catch (error) {
      log.warning("handler failed:", error);
    }
  }
}
