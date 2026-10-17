/* Shared undo/redo and local draft protection for Pages and local Editor.
 * Only EDL and non-sensitive source identifiers are stored; never media bytes.
 * No network requests. Draft restore always requires an explicit confirmation.
 */
(function (global) {
  "use strict";
  const VERSION = 1;
  const PREFIX = "movie-modify:edl-draft:v1:";
  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function hash(value) {
    const string = JSON.stringify(value);
    let first = 2166136261, second = 2166136261;
    for (let i = 0; i < string.length; i++) {
      const ch = string.charCodeAt(i);
      first = Math.imul(first ^ ch, 16777619);
      second = Math.imul(second ^ (ch ^ (i & 255)), 16777619);
    }
    return string.length + ":" + (first >>> 0).toString(16) + ":" + (second >>> 0).toString(16);
  }
  class EditHistory {
    constructor(config) {
      this.identity = clone(config.identity);
      this.key = PREFIX + String(config.key);
      this.storage = config.storage === undefined ? global.localStorage : config.storage;
      this.maxEntries = config.maxEntries || 40;
      this.onUpdate = config.onUpdate || (() => {});
      this.baseHash = hash(config.initial.segments);
      this.entries = [{snapshot: clone(config.initial), label: "開始", time: 0}];
      this.cursor = 0;
      this.available = true;
      this.lastError = "";
      this.onUpdate(this.state());
    }
    state() {
      return {canUndo: this.cursor > 0, canRedo: this.cursor < this.entries.length - 1,
        undoLabel: this.cursor > 0 ? this.entries[this.cursor].label : "",
        redoLabel: this.cursor < this.entries.length - 1 ? this.entries[this.cursor + 1].label : "",
        available: this.available, error: this.lastError};
    }
    current() { return clone(this.entries[this.cursor].snapshot); }
    checkpoint(snapshot, label = "編集", coalesce = false) {
      if (!snapshot || !Array.isArray(snapshot.segments)) throw Error("Missing timeline");
      const newEntry = {snapshot: clone(snapshot), label, time: Date.now()};
      const old = this.entries[this.cursor];
      if (equal(old.snapshot, newEntry.snapshot)) return false;
      this.entries.length = this.cursor + 1;
      const canMerge = coalesce && this.cursor > 0 && old.label === label &&
        Date.now() - old.time < 700;
      if (canMerge) this.entries[this.cursor] = newEntry;
      else { this.entries.push(newEntry); this.cursor++; }
      if (this.entries.length > this.maxEntries) {
        this.entries.shift(); this.cursor--;
      }
      this.persist(newEntry.snapshot);
      this.onUpdate(this.state());
      return true;
    }
    undo() {
      if (this.cursor === 0) return null;
      this.cursor--;
      this.persist(this.entries[this.cursor].snapshot);
      this.onUpdate(this.state());
      return this.current();
    }
    redo() {
      if (this.cursor >= this.entries.length - 1) return null;
      this.cursor++;
      this.persist(this.entries[this.cursor].snapshot);
      this.onUpdate(this.state());
      return this.current();
    }
    persist(snapshot = this.entries[this.cursor].snapshot) {
      try {
        this.storage.setItem(this.key, JSON.stringify({
          version: VERSION, identity: this.identity, baseline: this.baseHash,
          savedAt: Date.now(), snapshot: clone(snapshot)
        }));
        this.available = true; this.lastError = "";
        return true;
      } catch (error) {
        this.available = false;
        this.lastError = "ブラウザへの自動保存に失敗しました。編集JSONを手動保存してください。";
        this.onUpdate(this.state());
        return false;
      }
    }
    candidate() {
      let content;
      try { content = this.storage.getItem(this.key); }
      catch (_) { return {status: "unavailable"}; }
      if (!content) return {status: "empty"};
      try {
        const entry = JSON.parse(content);
        if (entry.version !== VERSION || !equal(entry.identity, this.identity) ||
            !entry.snapshot || !Array.isArray(entry.snapshot.segments) ||
            typeof entry.savedAt !== "number" ||
            entry.snapshot.segments.length < 1 || entry.snapshot.segments.length > 5000)
          return {status: "invalid"};
        if (entry.baseline !== this.baseHash) return {status: "conflict", savedAt: entry.savedAt};
        if (equal(entry.snapshot, this.current())) return {status: "unchanged"};
        return {status: "available", snapshot: clone(entry.snapshot), savedAt: entry.savedAt};
      } catch (_) { return {status: "invalid"}; }
    }
    restore(snapshot, validate) {
      const safe = validate(clone(snapshot));
      if (!safe || !Array.isArray(safe.segments)) throw Error("Invalid restored timeline");
      this.checkpoint(safe, "自動保存から復元");
      return safe;
    }
    // A successful manual server save changes the reference used for conflict detection.
    // Never erase a draft after a failed network save.
    markServerSaved(snapshot) {
      this.baseHash = hash(snapshot.segments);
      this.entries = [{snapshot: clone(snapshot), label: "保存済み", time: Date.now()}];
      this.cursor = 0;
      this.clear();
      this.onUpdate(this.state());
    }
    clear() {
      try { this.storage.removeItem(this.key); }
      catch (_) { /* Private mode/quota errors are reported by persist. */ }
    }
  }
  global.MovieModifyEditHistory = {EditHistory, clone, hash};
})(window);
