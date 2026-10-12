import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

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
