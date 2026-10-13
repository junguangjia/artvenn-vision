import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";
import fs from "node:fs";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const { sourceGroups, toggleSelection, assignPhotos, editSelected, patchValue, confirmationAllowed, saveAllowed } = require("../src/artvenn_vision/ui/review.js");

function fixture() {
  return {
    objects: [
      { object_id: "one", title: "First inscription", asset_ids: ["a", "b"] },
      { object_id: "two", title: "Second inscription", asset_ids: ["c"] },
    ],
    photos: {
      a: { object_id: "one", role: "detail", labels: { surfaces: ["front"], content: ["main_text"], notes: "Uncertain text" } },
      b: { object_id: "one", role: "overview", labels: { content: ["seal"] } },
      c: { object_id: "two", role: "context", labels: {} },
    },
  };
}

test("source proposals remain distinct and every prepared photo is available", () => {
  const snapshot = {
    assets: Array.from({ length: 101 }, (_, i) => ({ asset_id: "photo-" + i })),
    groups: [
      { key: "first", asset_ids: ["photo-0", "photo-1"] },
      { key: "second", asset_ids: ["photo-1", "photo-2"] },
    ],
  };
  const original = JSON.stringify(snapshot);
  const groups = sourceGroups(snapshot);
  assert.equal(groups.length, 3);
  assert.equal(groups[2].kind, "ungrouped");
  assert.equal(groups[2].asset_ids.length, 98);
  assert.equal(new Set(groups.flatMap((g) => g.asset_ids)).size, 101);
  assert.deepEqual(groups[1].asset_ids, ["photo-1", "photo-2"]);
  assert.equal(JSON.stringify(snapshot), original);
});

test("group and individual selections count duplicated appearances once", () => {
  const previous = new Set(["a"]);
  const selected = toggleSelection(previous, ["a", "b"], true);
  assert.equal(selected.size, 2);
  assert.deepEqual([...previous], ["a"]);
  assert.deepEqual([...toggleSelection(selected, ["a"], false)], ["b"]);
});

test("named assignment can combine groups and singles without changing source labels", () => {
  const original = fixture();
  const next = assignPhotos(original, ["a", "c", "a"], "new", "  Shared inscription  ");
  assert.deepEqual(next.objects.find((o) => o.object_id === "new"), { object_id: "new", title: "Shared inscription", asset_ids: ["a", "c"] });
  assert.deepEqual(next.objects.find((o) => o.object_id === "one").asset_ids, ["b"]);
  assert.equal(next.objects.find((o) => o.object_id === "two"), undefined);
  assert.deepEqual(next.photos.a.labels, original.photos.a.labels);
  assert.equal(next.photos.a.role, "detail");
  assert.equal(original.photos.a.object_id, "one");
  assert.throws(() => assignPhotos(original, ["outside"], "one", "Name"));
  assert.throws(() => assignPhotos(original, ["a"], "one", " "));
});

test("selected-only bulk edits preserve identity, purpose and other dimensions", () => {
  const original = fixture();
  const next = editSelected(original, ["a"], { axis: "content", operation: "add", value: ["seal"], multi: true });
  assert.deepEqual(next.photos.a.labels.content, ["main_text", "seal"]);
  assert.deepEqual(next.photos.b, original.photos.b);
  assert.equal(next.photos.a.object_id, "one");
  assert.equal(next.photos.a.role, "detail");
  assert.equal(next.photos.a.labels.notes, "Uncertain text");
  assert.deepEqual(original.photos.a.labels.content, ["main_text"]);
  const removed = editSelected(next, ["a"], { axis: "content", operation: "remove", value: ["seal"], multi: true });
  assert.deepEqual(removed.photos.a.labels.content, ["main_text"]);
  const cleared = editSelected(removed, ["a"], { axis: "content", operation: "clear", multi: true });
  assert.deepEqual(cleared.photos.a.labels.content, []);
});

test("clear is explicit, no-change is a no-op, uncertainty does not coexist with certainty", () => {
  assert.equal(patchValue("stone", "clear", null, false), null);
  assert.deepEqual(patchValue(["front"], "unchanged", ["back"], true), ["front"]);
  assert.deepEqual(patchValue(["front"], "add", ["unknown"], true), ["unknown"]);
  assert.deepEqual(patchValue(["unknown"], "add", ["back"], true), ["back"]);
  const draft = fixture();
  assert.deepEqual(editSelected(draft, ["a"], { axis: "content", operation: "unchanged", value: [], multi: true }), draft);
  assert.throws(() => editSelected(draft, ["missing"], { role: "detail" }));
});

test("human confirmation requires a saved complete revision and named reviewer", () => {
  const draft = fixture();
  assert.equal(confirmationAllowed({ revision: 0 }, draft, false, "Reviewer"), false);
  assert.equal(confirmationAllowed({ revision: 1 }, draft, true, "Reviewer"), false);
  assert.equal(confirmationAllowed({ revision: 1 }, draft, false, " "), false);
  assert.equal(confirmationAllowed({ revision: 1 }, draft, false, "Reviewer"), true);
  const emptyObject = { ...draft, objects: [...draft.objects, { object_id: "empty", title: "Provisional", asset_ids: [] }] };
  assert.equal(confirmationAllowed({ revision: 1 }, emptyObject, false, "Reviewer"), false);
  draft.photos.c.object_id = null;
  assert.equal(confirmationAllowed({ revision: 1 }, draft, false, "Reviewer"), false);
});

test("an unchanged initial AI draft can be saved before human confirmation", () => {
  const draft = fixture();
  assert.equal(saveAllowed(null, false), false);
  assert.equal(saveAllowed({ revision: 0 }, false), true);
  assert.equal(confirmationAllowed({ revision: 0 }, draft, false, "Reviewer"), false);
  assert.equal(saveAllowed({ revision: 1 }, false), false);
  assert.equal(confirmationAllowed({ revision: 1 }, draft, false, "Reviewer"), true);
  assert.equal(saveAllowed({ revision: 1 }, true), true);
});

const {
  selectionContext, pendingCount, projectPatch, valueState, stageChoice,
  stageClear, sideReferenceNeeded, applyInspectorPatch,
} = require("../src/artvenn_vision/ui/review.js");

test("mixed tags add to all, unanimous tags remove, and unrelated legacy labels survive", () => {
  const draft = fixture();
  draft.photos.a.labels.work_format = "folded_book";
  draft.photos.a.labels.parts = ["head"];
  const ids = ["a", "b"];
  assert.equal(valueState(draft, ids, "content", "seal"), "partial");
  let pending = stageChoice(draft, ids, {}, "content", "seal");
  assert.equal(pendingCount(pending), 1);
  assert.deepEqual(draft.photos.a.labels.content, ["main_text"]);
  let next = applyInspectorPatch(draft, ids, pending);
  assert.deepEqual(next.photos.a.labels.content, ["main_text", "seal"]);
  assert.deepEqual(next.photos.b.labels.content, ["seal"]);
  assert.deepEqual(next.photos.c, draft.photos.c);
  assert.equal(next.photos.a.labels.work_format, "folded_book");
  assert.deepEqual(next.photos.a.labels.parts, ["head"]);
  assert.equal(next.photos.a.labels.notes, "Uncertain text");
  pending = stageChoice(next, ids, {}, "content", "seal");
  next = applyInspectorPatch(next, ids, pending);
  assert.deepEqual(next.photos.a.labels.content, ["main_text"]);
  assert.deepEqual(next.photos.b.labels.content, []);
});

test("unknown is exclusive, while a positive tag replaces only uncertainty", () => {
  const draft = fixture();
  let pending = stageChoice(draft, ["a", "b"], {}, "content", "unknown");
  let next = applyInspectorPatch(draft, ["a", "b"], pending);
  assert.deepEqual(next.photos.a.labels.content, ["unknown"]);
  assert.deepEqual(next.photos.b.labels.content, ["unknown"]);
  pending = stageChoice(next, ["a", "b"], {}, "content", "main_text");
  next = applyInspectorPatch(next, ["a", "b"], pending);
  assert.deepEqual(next.photos.a.labels.content, ["main_text"]);
  assert.deepEqual(next.photos.b.labels.content, ["main_text"]);
  assert.equal(next.photos.a.labels.notes, "Uncertain text");
});

test("explicit framing synchronizes purpose; AI purpose is not inferred and clear preserves it", () => {
  const draft = fixture();
  assert.equal(draft.photos.b.role, "overview");
  assert.equal(valueState(draft, ["b"], "coverage", "whole_object"), "none");
  const pending = stageChoice(draft, ["a"], {}, "coverage", "whole_surface_page");
  const next = applyInspectorPatch(draft, ["a"], pending);
  assert.equal(next.photos.a.labels.coverage, "whole_surface_page");
  assert.equal(next.photos.a.role, "overview");
  assert.equal(draft.photos.a.role, "detail");
  assert.equal(draft.photos.a.labels.coverage, undefined);
  const cleared = applyInspectorPatch(next, ["a"], stageClear({}, "coverage"));
  assert.equal(cleared.photos.a.labels.coverage, null);
  assert.equal(cleared.photos.a.role, "overview");
  assert.deepEqual(cleared.photos.b, draft.photos.b);
});

test("left and right require explicit reference including when clearing an old reference", () => {
  const draft = fixture();
  let pending = stageChoice(draft, ["a", "b"], {}, "surfaces", "left");
  assert.equal(sideReferenceNeeded(projectPatch(draft, ["a", "b"], pending), ["a", "b"]), true);
  assert.throws(() => applyInspectorPatch(draft, ["a", "b"], pending), /facing the stele front/);
  pending = stageChoice(draft, ["a", "b"], pending, "side_reference", "facing_front");
  const next = applyInspectorPatch(draft, ["a", "b"], pending);
  assert.deepEqual(next.photos.a.labels.surfaces, ["front", "left"]);
  assert.equal(next.photos.a.labels.side_reference, "facing_front");
  assert.throws(() => applyInspectorPatch(next, ["a"], stageClear({}, "side_reference")), /facing the stele front/);
  assert.equal(next.photos.a.labels.side_reference, "facing_front");
});

test("staged patch context binds unique selected photos and their assigned objects", () => {
  const draft = fixture();
  const context = selectionContext(draft, ["b", "a", "a"]);
  assert.equal(context, selectionContext(draft, ["a", "b"]));
  const pending = stageChoice(draft, ["a", "b"], {}, "representation", "stone");
  const reassigned = assignPhotos(draft, ["b"], "two", "Second inscription");
  assert.throws(() => applyInspectorPatch(reassigned, ["a", "b"], pending, context), /assigned objects changed/);
  assert.throws(() => applyInspectorPatch(draft, ["a"], pending, context), /assigned objects changed/);
  const unassigned = structuredClone(draft); unassigned.photos.a.object_id = null;
  assert.throws(() => applyInspectorPatch(unassigned, ["a"], pending), /named object first/);
  assert.throws(() => applyInspectorPatch(draft, ["missing"], pending), /prepared photos/);
});

test("pending labels block save and human confirmation until Apply or Discard", () => {
  const draft = fixture();
  assert.equal(saveAllowed({ revision: 0 }, false, true), false);
  assert.equal(saveAllowed({ revision: 1 }, true, true), false);
  assert.equal(confirmationAllowed({ revision: 1 }, draft, false, "Reviewer", true), false);
  assert.equal(confirmationAllowed({ revision: 1 }, draft, false, "Reviewer", false), true);
  assert.equal(saveAllowed({ revision: 1 }, true, false), true);
});

// A dependency-free DOM harness runs the real page script and callbacks. Pure
// patch tests above cover semantics; these checks cover wiring and action guards.
class Element {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.attrs = {}; this.dataset = {};
    this.value = ""; this.disabled = false; this.checked = false; this.indeterminate = false;
    this._text = ""; this.classes = new Set();
    this.classList = { toggle: (key, enabled) => enabled ? this.classes.add(key) : this.classes.delete(key) };
  }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map((child) => child.textContent).join(""); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this._text = ""; }
  setAttribute(key, value) { this.attrs[key] = String(value); }
  focus() { this.focused = true; }
  scrollIntoView(options) { this.scrollOptions = options; }
  querySelectorAll(selector) {
    const tags = new Set(selector.split(",").map((item) => item.trim().toUpperCase()));
    const found = [];
    for (const child of this.children) {
      if (tags.has(child.tagName)) found.push(child);
      found.push(...child.querySelectorAll(selector));
    }
    return found;
  }
}
const uiScript = fs.readFileSync(new URL("../src/artvenn_vision/ui/review.js", import.meta.url), "utf8");
const uiHtml = fs.readFileSync(new URL("../src/artvenn_vision/ui/index.html", import.meta.url), "utf8");
const taxonomyFixture = JSON.parse(fs.readFileSync(new URL("../src/artvenn_vision/schemas/photo-annotation-v1.schema.json", import.meta.url), "utf8")).oneOf[0].properties.values.properties;
async function pageHarness(options = {}) {
  const body = new Element("body");
  const ids = new Map();
  for (const match of uiHtml.matchAll(/<([a-z][a-z0-9]*)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const element = new Element(match[1]); element.id = match[2]; ids.set(element.id, element); body.append(element);
  }
  const config = new Element("script"); config.id = "session-config";
  config.textContent = JSON.stringify({ csrfToken: "synthetic-session-placeholder" }); ids.set(config.id, config); body.append(config);
  const current = { revision: 1, confirmed_revision: null, draft: fixture(), taxonomy: taxonomyFixture,
    assets: ["a", "b", "c"].map((asset_id) => ({ asset_id })),
    groups: [{ key: "first", asset_ids: ["a", "b"] }, { key: "overlap", asset_ids: ["b"] }],
    processed_asset_ids: ["a", "b"], ...options.snapshot };
  const calls = []; const events = {}; const deferred = new Map();
  const document = {
    createElement: (tag) => new Element(tag),
    getElementById: (id) => ids.get(id) || all().find((node) => node.id === id),
    querySelectorAll: (selector) => body.querySelectorAll(selector),
  };
  function all() {
    const found = []; const walk = (element) => { found.push(element); for (const child of element.children) walk(child); }; walk(body); return found;
  }
  const context = vm.createContext({ document, window: { confirm: () => true, addEventListener: (key, handler) => { events[key] = handler; } },
    crypto: { randomUUID: () => "synthetic-object-id" }, console,
    fetch: async (path, init = {}) => {
      calls.push({ path, init });
      if (options.defer === path) await new Promise((resolve) => deferred.set(path, resolve));
      const response = options.responses?.[path];
      if (response) return { ok: response.status < 400, status: response.status, json: async () => response.body };
      return { ok: true, status: 200, json: async () => structuredClone(current) };
    } });
  vm.runInContext(uiScript, context); await new Promise(setImmediate);
  return { document, current, calls, events, deferred, all, q: (id) => document.getElementById(id),
    chip: (axis, value) => all().find((node) => node.dataset.axis === axis && node.dataset.value === value),
    named: (aria) => all().filter((node) => node.attrs["aria-label"] === aria) };
}

function changeCheck(control, checked) { control.checked = checked; control.onchange(); }

test("real UI uses one direct inspector, deduplicates tiles, and blocks actions while pending", async () => {
  const page = await pageHarness();
  assert.equal(page.all().filter((node) => node.tagName === "DETAILS").length, 0);
  assert.equal(page.named("Select photo b").length, 2);
  changeCheck(page.named("Select source group first")[0], true);
  assert.equal(page.q("selected-count").textContent, "2 unique photos selected");
  assert.ok(page.named("Select photo b").every((check) => check.checked));
  assert.equal(page.chip("content", "seal").attrs["aria-pressed"], "mixed");
  page.chip("content", "seal").onclick();
  assert.equal(page.chip("content", "seal").attrs["aria-pressed"], "true");
  for (const id of ["save", "confirm", "export", "reload"]) assert.equal(page.q(id).disabled, true, id);
  assert.equal(page.q("apply-inspector").disabled, false);
  const before = page.calls.length;
  page.q("save").onclick(); page.q("confirm").onclick(); page.q("export").onclick(); page.q("reload").onclick();
  await new Promise(setImmediate); assert.equal(page.calls.length, before);
  page.q("apply-inspector").onclick();
  assert.equal(page.q("discard-inspector").disabled, true);
  assert.equal(page.q("save").disabled, false);
  assert.equal(page.q("confirm").disabled, true);
  assert.equal(page.q("export").disabled, true);
  assert.ok(page.all().filter((node) => node.className === "photo-labels").some((node) => node.textContent.includes("Main text · Seal")));
  assert.equal(page.calls.length, before);
});

test("single-photo editing invalidates a batch patch and changes no draft values", async () => {
  const page = await pageHarness();
  changeCheck(page.named("Select source group first")[0], true);
  page.chip("content", "seal").onclick();
  page.named("Label only photo a")[0].onclick();
  assert.equal(page.q("selected-count").textContent, "1 unique photos selected");
  assert.equal(page.q("inspector").focused, true);
  assert.equal(page.q("inspector").scrollOptions.block, "nearest");
  assert.equal(page.q("inspector").scrollOptions.inline, "nearest");
  assert.equal(page.q("discard-inspector").disabled, true);
  assert.match(page.q("batch-status").textContent, /discarded.*selected photos/);
  assert.equal(page.chip("content", "seal").attrs["aria-pressed"], "false");
  assert.equal(page.q("save").disabled, true);
  assert.ok(page.named("Select photo b").every((check) => !check.checked));
});

test("changing an assigned object discards pending labels even when selected IDs stay identical", async () => {
  const page = await pageHarness();
  page.named("Label only photo a")[0].onclick();
  page.chip("representation", "stone").onclick();
  const cardObject = page.all().find((node) => node.tagName === "SELECT" && node.value === "one" && !node.id);
  cardObject.value = "two"; cardObject.onchange();
  assert.equal(page.q("selected-count").textContent, "1 unique photos selected");
  assert.equal(page.q("discard-inspector").disabled, true);
  assert.match(page.q("batch-status").textContent, /object assignment changed/);
  assert.equal(page.chip("representation", "stone").attrs["aria-pressed"], "false");
  assert.equal(page.q("save").disabled, false);
});

test("side confirmation and discard are wired without assuming orientation", async () => {
  const page = await pageHarness();
  page.named("Label only photo a")[0].onclick();
  page.chip("surfaces", "left").onclick();
  assert.equal(page.q("apply-inspector").disabled, true);
  assert.equal(page.q("facing-front").checked, false);
  changeCheck(page.q("facing-front"), true);
  assert.equal(page.q("apply-inspector").disabled, false);
  page.q("discard-inspector").onclick();
  assert.equal(page.chip("surfaces", "left").attrs["aria-pressed"], "false");
  assert.equal(page.q("facing-front").checked, false);
  assert.equal(page.q("save").disabled, true);
});

test("dirty or pending drafts warn on exit; selection alone does not", async () => {
  const page = await pageHarness();
  let prevented = false;
  const event = { preventDefault: () => { prevented = true; } };
  page.named("Label only photo a")[0].onclick(); page.events.beforeunload(event);
  assert.equal(prevented, false);
  page.chip("coverage", "detail").onclick(); page.events.beforeunload(event);
  assert.equal(prevented, true);
  page.q("discard-inspector").onclick(); prevented = false; page.events.beforeunload(event);
  assert.equal(prevented, false);
  page.chip("coverage", "whole_object").onclick(); page.q("apply-inspector").onclick(); page.events.beforeunload(event);
  assert.equal(prevented, true);
});

test("conflict keeps edits, blocks programmatic editing, and leaves reload available", async () => {
  const page = await pageHarness({ responses: { "/api/save": { status: 409, body: { message: "revision_conflict" } } } });
  page.named("Label only photo a")[0].onclick();
  page.chip("coverage", "whole_object").onclick(); page.q("apply-inspector").onclick();
  page.q("save").onclick(); await new Promise(setImmediate);
  assert.match(page.q("notice").textContent, /unsaved edits remain/);
  assert.equal(page.q("reload").disabled, false);
  assert.equal(page.q("save").disabled, true);
  assert.equal(page.q("select-all").disabled, true);
  assert.ok(page.chip("representation", "stone").disabled);
  page.q("select-all").onclick(); page.chip("representation", "stone").onclick();
  assert.equal(page.q("selected-count").textContent, "1 unique photos selected");
  assert.equal(page.q("discard-inspector").disabled, true);
  assert.equal(page.calls.filter((call) => call.path === "/api/save").length, 1);
});

test("busy actions block programmatic callbacks as well as visible controls", async () => {
  const page = await pageHarness({ defer: "/api/save" });
  page.named("Label only photo a")[0].onclick();
  page.chip("content", "seal").onclick(); page.q("apply-inspector").onclick();
  page.q("save").onclick(); await new Promise(setImmediate);
  assert.equal(page.q("select-all").disabled, true);
  page.q("select-all").onclick(); page.chip("representation", "stone").onclick(); page.q("save").onclick();
  assert.equal(page.q("selected-count").textContent, "1 unique photos selected");
  assert.equal(page.calls.filter((call) => call.path === "/api/save").length, 1);
  page.deferred.get("/api/save")(); await new Promise(setImmediate);
  assert.equal(page.q("select-all").disabled, false);
});
