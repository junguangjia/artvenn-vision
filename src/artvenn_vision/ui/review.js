/* Local drafts and human decisions; no inference, upload or publication. */
(() => {
  "use strict";
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  const uncertainty = new Set(["unknown", "not_applicable"]);
  const roleNames = { overview: "Overall view", detail: "Detail", label: "Exhibition label", context: "Environment", unspecified: "Unspecified" };
  const coverageRoles = { whole_object: "overview", whole_surface_page: "overview", detail: "detail", context: "context", label: "label", unknown: "unspecified" };
  const valueNames = {
    stone: "Original stone", ink_original: "Original ink", rubbing: "Rubbing", facsimile: "Copy", unknown: "Unknown",
    whole_object: "Whole object", whole_surface_page: "Whole face / page", detail: "Detail", context: "Setting", label: "Exhibition label",
    front: "Front (yang)", back: "Back (yin)", side_unspecified: "Side, unidentified", left: "Left side", right: "Right side",
    main_work: "Main work", frontispiece: "Frontispiece", tail: "Tail section", cover_mount: "Cover / mounting", leaf_page: "Leaf / page",
    main_text: "Main text", stele_title: "Stele title", colophon: "Colophon", title_slip: "Title slip", signature: "Signature / inscription", seal: "Seal",
  };
  const name = (value) => valueNames[value] || String(value).replaceAll("_", " ");
  const inspectorAxes = {
    representation: ["stone", "ink_original", "rubbing", "facsimile", "unknown"],
    coverage: ["whole_object", "whole_surface_page", "detail", "context", "label", "unknown"],
    surfaces: ["front", "back", "side_unspecified", "left", "right", "unknown"],
    positions: ["main_work", "frontispiece", "tail", "cover_mount", "leaf_page", "unknown"],
    content: ["main_text", "stele_title", "colophon", "title_slip", "signature", "seal", "unknown"],
  };
  const multiAxes = new Set(["surfaces", "positions", "content"]);

  function sourceGroups(snapshot) {
    const available = new Set(snapshot.assets.map((a) => a.asset_id));
    const groups = snapshot.groups.map((group, index) => ({
      key: group.key || group.group_id || "source-" + (index + 1),
      asset_ids: [...new Set(group.asset_ids)].filter((id) => available.has(id)),
      kind: "ai", fields: group.fields || {},
    })).filter((group) => group.asset_ids.length);
    const grouped = new Set(groups.flatMap((group) => group.asset_ids));
    const remaining = snapshot.assets.map((a) => a.asset_id).filter((id) => !grouped.has(id));
    if (remaining.length) groups.push({ key: "ungrouped", asset_ids: remaining, kind: "ungrouped", fields: {} });
    return groups;
  }
  function toggleSelection(selection, assetIds, enabled) {
    const next = new Set(selection);
    for (const id of assetIds) enabled ? next.add(id) : next.delete(id);
    return next;
  }
  function synchronizeMemberships(draft) {
    for (const object of draft.objects)
      object.asset_ids = Object.entries(draft.photos).filter(([, photo]) => photo.object_id === object.object_id).map(([id]) => id);
    // Prior revisions and AI source proposals retain their original memberships.
    draft.objects = draft.objects.filter((object) => object.asset_ids.length);
    return draft;
  }
  function assignPhotos(draft, assetIds, objectId, title) {
    const next = copy(draft);
    const ids = [...new Set(assetIds)];
    if (!ids.length || ids.some((id) => !Object.hasOwn(next.photos, id))) throw new Error("Select prepared photos before assigning an object.");
    if (!objectId || !title?.trim()) throw new Error("Enter a nonblank object title.");
    let object = next.objects.find((item) => item.object_id === objectId);
    if (!object) {
      object = { object_id: objectId, title: title.trim(), asset_ids: [] };
      next.objects.push(object);
    } else object.title = title.trim();
    for (const id of ids) next.photos[id].object_id = objectId;
    return synchronizeMemberships(next);
  }
  function patchValue(current, operation, value, multi) {
    if (operation === "unchanged") return current;
    if (operation === "clear") return multi ? [] : null;
    if (!multi || operation === "set") return multi ? [...value].sort() : value;
    let result = operation === "add" ? [...new Set([...(current || []), ...value])] : (current || []).filter((item) => !value.includes(item));
    if (operation === "add" && value.some((item) => uncertainty.has(item))) result = [...value];
    else if (result.length > 1) result = result.filter((item) => !uncertainty.has(item));
    return result.sort();
  }
  function editSelected(draft, assetIds, { axis, operation, value, multi = false, role }) {
    const next = copy(draft);
    for (const id of new Set(assetIds)) {
      if (!Object.hasOwn(next.photos, id)) throw new Error("The selection includes a photo outside this review.");
      const photo = next.photos[id];
      if (role !== undefined) photo.role = role;
      if (axis && operation !== "unchanged") {
        photo.labels ||= {};
        photo.labels[axis] = patchValue(photo.labels[axis], operation, value, multi);
      }
    }
    return next;
  }
  function selectionContext(draft, assetIds) {
    return JSON.stringify([...new Set(assetIds)].sort().map((id) => [id, draft.photos[id]?.object_id ?? null]));
  }
  function pendingCount(pending) {
    return Object.values(pending).reduce((count, edits) => count + edits.length, 0);
  }
  function projectPatch(draft, assetIds, pending) {
    let next = copy(draft);
    for (const [axis, edits] of Object.entries(pending))
      for (const edit of edits) {
        next = editSelected(next, assetIds, { axis, ...edit, multi: multiAxes.has(axis) });
        // Only an explicit framing choice changes the legacy purpose. Clearing
        // framing never interprets an existing AI purpose as a human label.
        if (axis === "coverage" && edit.operation === "set" && Object.hasOwn(coverageRoles, edit.value))
          next = editSelected(next, assetIds, { role: coverageRoles[edit.value] });
      }
    return next;
  }
  function valueState(draft, assetIds, axis, value) {
    const ids = [...new Set(assetIds)];
    if (!ids.length) return "none";
    const count = ids.filter((id) => {
      const current = draft.photos[id]?.labels?.[axis];
      return multiAxes.has(axis) ? (current || []).includes(value) : same(current, value);
    }).length;
    return count === ids.length ? "all" : count ? "partial" : "none";
  }
  function stageChoice(draft, assetIds, pending, axis, value) {
    const next = copy(pending);
    const projected = projectPatch(draft, assetIds, pending);
    const operation = multiAxes.has(axis) ? valueState(projected, assetIds, axis, value) === "all" ? "remove" : "add" : "set";
    next[axis] ||= [];
    next[axis].push({ operation, value: multiAxes.has(axis) ? [value] : value });
    return next;
  }
  function stageClear(pending, axis) {
    return { ...copy(pending), [axis]: [{ operation: "clear", value: null }] };
  }
  function sideReferenceNeeded(draft, assetIds) {
    return [...new Set(assetIds)].some((id) => {
      const values = draft.photos[id]?.labels || {};
      return (values.surfaces || []).some((value) => value === "left" || value === "right") && values.side_reference !== "facing_front";
    });
  }
  function applyInspectorPatch(draft, assetIds, pending, context = selectionContext(draft, assetIds)) {
    const ids = [...new Set(assetIds)];
    if (!ids.length || ids.some((id) => !Object.hasOwn(draft.photos, id))) throw new Error("Select prepared photos before applying labels.");
    if (selectionContext(draft, ids) !== context) throw new Error("The selected photos or their assigned objects changed. Choose the labels again.");
    if (ids.some((id) => !draft.photos[id].object_id)) throw new Error("Assign every selected photo to a named object first.");
    const next = projectPatch(draft, ids, pending);
    if (sideReferenceNeeded(next, ids)) throw new Error("Confirm that left and right are identified while facing the stele front.");
    return next;
  }
  function confirmationAllowed(snapshot, draft, dirty, reviewer, pending = false) {
    return !!snapshot && snapshot.revision > 0 && !dirty && !pending && !!reviewer.trim() &&
      draft.objects.length > 0 && draft.objects.every((object) => object.title.trim() && object.asset_ids.length) &&
      Object.values(draft.photos).every((photo) => photo.object_id && draft.objects.some((object) => object.object_id === photo.object_id && object.title.trim()));
  }
  function saveAllowed(snapshot, dirty, pending = false) {
    return !!snapshot && !pending && (snapshot.revision === 0 || dirty);
  }
  const helpers = { sourceGroups, toggleSelection, assignPhotos, editSelected, patchValue, selectionContext, pendingCount, projectPatch, valueState, stageChoice, stageClear, sideReferenceNeeded, applyInspectorPatch, confirmationAllowed, saveAllowed };
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  if (typeof document === "undefined") return;

  const q = (id) => document.getElementById(id);
  const config = JSON.parse(q("session-config").textContent);
  let snapshot = null;
  let draft = null;
  let selection = new Set();
  let dirty = false;
  let busy = false;
  let conflict = false;
  let taxonomy = {};
  let pending = {};
  let pendingContext = null;
  let mode = "stele";
  const cards = new Map();
  const groupChecks = [];
  const node = (tag, text) => {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    return result;
  };
  const label = (text, control) => {
    const result = node("label", text);
    result.append(control);
    return result;
  };
  function button(text, click, className = "") {
    const control = node("button", text); control.type = "button"; control.className = className; control.onclick = click;
    return control;
  }
  function selectControl(values, value, change) {
    const control = node("select");
    for (const [key, text] of values) {
      const option = node("option", text); option.value = key ?? ""; control.append(option);
    }
    control.value = value ?? "";
    control.onchange = () => change(control.value);
    return control;
  }
  function announce(text, error = false) {
    q("notice").textContent = text;
    q("notice").classList.toggle("error", error);
  }
  function canEdit() { return !!draft && !busy && !conflict; }
  function canLabel() { return canEdit() && selection.size > 0 && [...selection].every((id) => draft.photos[id]?.object_id); }
  function discardPending(message) {
    pending = {}; pendingContext = null;
    if (message) q("batch-status").textContent = message;
  }
  function reconcilePending() {
    if (pendingCount(pending) && pendingContext !== selectionContext(draft, selection))
      discardPending("Unapplied labels were discarded because the selected photos or their object assignment changed.");
  }
  function updated(next) {
    if (same(next, draft)) return;
    draft = next;
    dirty = true;
    q("export-result").replaceChildren();
    updateActions();
  }
  function updateActions() {
    const ready = !!snapshot && !busy && !conflict;
    if (draft) reconcilePending();
    const staged = pendingCount(pending) > 0;
    q("save").disabled = !ready || !saveAllowed(snapshot, dirty, staged);
    q("confirm").disabled = !ready || !confirmationAllowed(snapshot, draft, dirty, q("reviewer").value, staged) || snapshot.confirmed_revision === snapshot.revision;
    q("export").disabled = !ready || staged || dirty || snapshot.confirmed_revision !== snapshot.revision;
    q("reload").disabled = busy || staged;
    q("reviewer").disabled = busy || conflict;
    q("revision-status").textContent = snapshot ? "Saved revision " + snapshot.revision + " · " + (dirty ? "Unsaved changes" : snapshot.confirmed_revision === snapshot.revision ? "Human confirmed" : "Draft, not confirmed") : "";
    q("confirmation-help").textContent = staged ? "Apply or discard the pending labels before saving, confirming, exporting or reloading." : dirty ? "Save these edits before confirming. Confirmation uses the saved revision." : snapshot?.confirmed_revision === snapshot?.revision && snapshot ? "The saved revision is confirmed. Further edits create a new draft." : "Assign every photo to a named object and enter your reviewer name before confirming.";
    updateSelection();
  }
  function updateSelection() {
    if (draft) reconcilePending();
    q("selected-count").textContent = selection.size + " unique photos selected";
    q("select-all").disabled = !canEdit();
    q("clear-selection").disabled = !canEdit() || !selection.size;
    q("assignment-target").disabled = !canEdit();
    q("assignment-title").disabled = !canEdit();
    q("assign").disabled = !canEdit() || !selection.size || !q("assignment-title").value.trim();
    for (const [id, entries] of cards)
      for (const { tile, check, single, object } of entries) {
        check.checked = selection.has(id); check.disabled = !canEdit();
        single.disabled = !canEdit(); object.disabled = !canEdit();
        tile.classList.toggle("selected", check.checked);
      }
    for (const { check, ids } of groupChecks) {
      const count = ids.filter((id) => selection.has(id)).length;
      check.checked = count === ids.length; check.disabled = !canEdit();
      check.indeterminate = count > 0 && count < ids.length;
    }
    renderInspector();
    // Selection changes can discard staged labels, so refresh these guards too.
    const staged = pendingCount(pending) > 0;
    const ready = !!snapshot && !busy && !conflict;
    q("save").disabled = !ready || !saveAllowed(snapshot, dirty, staged);
    q("confirm").disabled = !ready || !confirmationAllowed(snapshot, draft, dirty, q("reviewer").value, staged) || snapshot.confirmed_revision === snapshot.revision;
    q("export").disabled = !ready || staged || dirty || snapshot.confirmed_revision !== snapshot.revision;
    q("reload").disabled = busy || staged;
  }
  function stage(axis, value) {
    if (!canLabel()) return;
    pendingContext ||= selectionContext(draft, selection);
    pending = stageChoice(draft, selection, pending, axis, value);
    updateActions();
  }
  function clearAxis(axis) {
    if (!canLabel()) return;
    pendingContext ||= selectionContext(draft, selection);
    pending = stageClear(pending, axis);
    updateActions();
  }
  function renderInspector() {
    const root = q("inspector-fields"); root.replaceChildren();
    q("inspector-count").textContent = selection.size === 1 ? "Label this photo" : "Label " + selection.size + " selected photos";
    const staged = pendingCount(pending) > 0;
    q("pending-status").textContent = staged ? "Pending labels — apply to the current selection or discard." : selection.size ? "Click a label to stage it. Other labels stay unchanged." : "Select a photo or group. All editing choices appear here.";
    q("selection-help").textContent = selection.size && !canLabel() && canEdit() ? "Assign every selected photo to a named object before labeling." : "Mixed labels show ‘some’. Click to add to all; click a label present on all to remove it.";
    const projected = draft ? projectPatch(draft, selection, pending) : null;
    for (const [key, title] of [["representation", "Carrier"], ["coverage", "Framing"], [mode === "stele" ? "surfaces" : "positions", mode === "stele" ? "Stele face · select all visible" : "Work position · select all visible"], ["content", "Visible text and seals · select all visible"]]) {
      if (!Object.hasOwn(taxonomy, key)) continue;
      const field = node("section"); field.className = "inspector-field";
      const header = node("div"); header.className = "field-heading";
      const clear = button("Clear", () => clearAxis(key), "clear-field"); clear.disabled = !canLabel(); clear.setAttribute("aria-label", "Clear " + title);
      header.append(node("h3", title), clear);
      const choices = node("div"); choices.className = "chip-row";
      for (const value of inspectorAxes[key]) {
        const state = projected ? valueState(projected, selection, key, value) : "none";
        const chip = button(name(value) + (state === "partial" ? " · some" : ""), () => stage(key, value), "label-chip");
        chip.dataset.axis = key; chip.dataset.value = value; chip.dataset.state = state;
        chip.setAttribute("aria-pressed", state === "partial" ? "mixed" : String(state === "all"));
        chip.setAttribute("aria-label", title + ": " + name(value) + (state === "partial" ? " (some selected photos)" : ""));
        chip.disabled = !canLabel(); choices.append(chip);
      }
      field.append(header, choices);
      if (key === "surfaces") {
        const reference = node("input"); reference.type = "checkbox"; reference.id = "facing-front";
        const state = projected ? valueState(projected, selection, "side_reference", "facing_front") : "none";
        reference.checked = state === "all"; reference.indeterminate = state === "partial"; reference.disabled = !canLabel();
        reference.onchange = () => {
          if (!canLabel()) return;
          pendingContext ||= selectionContext(draft, selection);
          pending = reference.checked ? stageChoice(draft, selection, pending, "side_reference", "facing_front") : stageClear(pending, "side_reference");
          updateActions();
        };
        const help = label("I identify left / right while facing the stele front", reference); help.className = "side-confirmation";
        field.append(help);
        if (projected && sideReferenceNeeded(projected, selection)) { const warning = node("p", "Left / right needs the confirmation above before Apply."); warning.className = "field-warning"; field.append(warning); }
      }
      root.append(field);
    }
    const versionVisible = !!projected && [...selection].some((id) => ["rubbing", "facsimile"].includes(projected.photos[id].labels?.representation) || projected.photos[id].labels?.version_label);
    if (versionVisible) {
      const values = [...selection].map((id) => projected.photos[id].labels?.version_label ?? "");
      const input = node("input"); input.type = "text"; input.maxLength = taxonomy.version_label?.maxLength || 120;
      input.id = "version-label"; input.value = values.every((value) => same(value, values[0])) ? values[0] : "";
      input.placeholder = values.some((value) => !same(value, values[0])) ? "Mixed versions — type to replace" : "Optional known copy or rubbing ID";
      input.disabled = !canLabel();
      input.oninput = () => {
        if (!canLabel()) return;
        pendingContext ||= selectionContext(draft, selection);
        pending = { ...pending, version_label: [{ operation: input.value.trim() ? "set" : "clear", value: input.value.trim() || null }] };
        // Preserve the input and cursor while typing; update only action guards.
        q("pending-status").textContent = "Pending labels — apply to the current selection or discard.";
        updatePendingActions();
      };
      const field = node("section"); field.className = "inspector-field";
      field.append(label("Rubbing / copy ID (optional)", input)); root.append(field);
    }
    for (const control of q("inspector-mode").querySelectorAll("button")) { control.disabled = busy || conflict; control.setAttribute("aria-pressed", String(control.dataset.mode === mode)); }
    updatePendingActions(projected);
  }
  function updatePendingActions(projected = draft ? projectPatch(draft, selection, pending) : null) {
    const staged = pendingCount(pending) > 0;
    q("apply-inspector").textContent = "Apply to " + selection.size + (selection.size === 1 ? " photo" : " photos");
    q("apply-inspector").disabled = !canLabel() || !staged || sideReferenceNeeded(projected, selection);
    q("discard-inspector").disabled = busy || conflict || !staged;
    if (staged) {
      for (const id of ["save", "confirm", "export", "reload"]) q(id).disabled = true;
      q("confirmation-help").textContent = "Apply or discard the pending labels before saving, confirming, exporting or reloading.";
    }
  }
  function photoSummary(photo) {
    const values = photo.labels || {};
    const labels = ["representation", "coverage", "surfaces", "positions", "content", "version_label"].flatMap((key) => {
      const value = values[key]; return Array.isArray(value) ? value.map(name) : value ? [key === "version_label" ? "Copy: " + value : name(value)] : [];
    });
    return labels.length ? labels.join(" · ") : "No human labels yet";
  }
  function buildPhoto(asset) {
    const id = asset.asset_id;
    const tile = node("article"); tile.className = "photo-card";
    const image = node("img"); image.src = "/previews/" + encodeURIComponent(id) + ".jpg"; image.alt = "Prepared photo " + id; image.loading = "lazy";
    const check = node("input"); check.type = "checkbox"; check.setAttribute("aria-label", "Select photo " + id);
    check.onchange = () => { if (!canEdit()) return; selection = toggleSelection(selection, [id], check.checked); updateSelection(); };
    const selectionLabel = label("Select this photo", check); selectionLabel.className = "photo-selection";
    const single = button("Label this photo", () => { if (!canEdit()) return; selection = new Set([id]); updateSelection();
      const inspector = q("inspector"); inspector.focus({ preventScroll: true });
      // Sticky panels can be displaced by the end of their parent near the last
      // group. Move only enough to expose the inspector, preserving this photo.
      inspector.scrollIntoView({ block: "nearest", inline: "nearest" }); });
    single.setAttribute("aria-label", "Label only photo " + id);
    const title = node("p", id); title.className = "photo-id";
    tile.append(image, title, selectionLabel, single);
    const object = selectControl([["", "Not assigned"], ...draft.objects.map((o) => [o.object_id, o.title])], draft.photos[id].object_id, (value) => {
      if (!canEdit()) return;
      const next = copy(draft); next.photos[id].object_id = value || null; updated(synchronizeMemberships(next)); render();
    });
    tile.append(label("Assigned object", object));
    const badges = node("p", photoSummary(draft.photos[id])); badges.className = "photo-labels"; tile.append(badges);
    const purpose = node("p", "Purpose: " + (roleNames[draft.photos[id].role] || draft.photos[id].role) + (draft.photos[id].labels?.coverage ? " · framing labeled" : " · framing not labeled")); purpose.className = "photo-purpose";
    tile.append(purpose);
    if (!cards.has(id)) cards.set(id, []);
    cards.get(id).push({ tile, check, single, object });
    return tile;
  }
  function rebuildAssignmentTargets(value = q("assignment-target").value || "new") {
    const control = q("assignment-target"); control.replaceChildren();
    for (const [id, title] of [["new", "Create a named object"], ...draft.objects.map((o) => [o.object_id, o.title])]) {
      const option = node("option", title); option.value = id; control.append(option);
    }
    control.value = draft.objects.some((o) => o.object_id === value) ? value : "new";
  }
  function render() {
    cards.clear(); groupChecks.length = 0;
    const groups = sourceGroups(snapshot); const root = q("photo-groups"); root.replaceChildren();
    const processed = snapshot.processed_asset_ids?.length ?? new Set(groups.filter((g) => g.kind === "ai").flatMap((g) => g.asset_ids)).size;
    q("summary").textContent = snapshot.assets.length + " prepared photos · " + processed + " processed · " + (snapshot.assets.length - processed) + " unprocessed · all photos available below";
    for (const [index, group] of groups.entries()) {
      const section = node("section"); section.className = "source-group";
      const header = node("div"); header.className = "source-header";
      header.append(node("h2", (group.kind === "ai" ? "AI source group " + (index + 1) : "Photos without an AI group") + " · " + group.asset_ids.length + " photos"));
      const check = node("input"); check.type = "checkbox"; check.setAttribute("aria-label", "Select source group " + group.key);
      check.onchange = () => { if (!canEdit()) return; selection = toggleSelection(selection, group.asset_ids, check.checked); updateSelection(); };
      groupChecks.push({ check, ids: group.asset_ids }); header.append(label("Select this source group", check));
      header.append(node("p", group.kind === "ai" ? "Source proposal preserved. Your assignment and labels are saved separately." : "Prepared photos remain selectable even when inference is unfinished or did not return a group."));
      const grid = node("div"); grid.className = "photo-grid";
      for (const id of group.asset_ids) grid.append(buildPhoto(snapshot.assets.find((a) => a.asset_id === id)));
      section.append(header, grid); root.append(section);
    }
    rebuildAssignmentTargets(); updateActions();
  }
  async function request(path, data) {
    const response = await fetch(path, data === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-ArtVenn-Session": config.csrfToken }, body: JSON.stringify(data) });
    const value = await response.json();
    if (!response.ok) {
      if (response.status === 409) conflict = true;
      const category = value.message || value.error_category || value.category || value.error || "Request failed";
      const reason = {
        annotation_side_reference_required: "Confirm the facing-front reference before applying left or right labels.",
        annotation_uncertainty_conflict: "Unknown cannot be combined with definite labels in the same dimension.",
        annotation_value_invalid: "A label is invalid. Check the available choices and text length.",
        review_unassigned_photos: "Assign every prepared photo to a named object before confirming.",
        review_object_name_required: "Give every assigned object a nonblank title before confirming.",
        reviewer_required: "Enter a nonblank reviewer name before confirming.",
        review_must_be_saved: "Save a local draft before confirming or exporting.",
        session_refused: "The local session has changed. Reload this workspace to reconnect.",
      }[category] || category;
      throw new Error(response.status === 409 ? "The saved revision changed. Your unsaved edits remain on this page. Reload the saved review before applying them again. " + reason : String(reason));
    }
    return value;
  }
  function accept(value) {
    snapshot = value.review || value; draft = copy(snapshot.draft); taxonomy = snapshot.taxonomy || {};
    dirty = false; conflict = false; discardPending();
    selection = new Set([...selection].filter((id) => Object.hasOwn(draft.photos, id)));
    const kinds = [...selection].map((id) => draft.photos[id].labels?.object_kind);
    if (kinds.length && kinds.every((kind) => kind === "calligraphy")) mode = "calligraphy";
    render();
  }
  async function operate(path, data, onSuccess) {
    if (busy || pendingCount(pending)) return;
    busy = true;
    document.querySelectorAll("button, input, select").forEach((control) => { control.disabled = true; });
    announce("Working locally…");
    try { onSuccess(await request(path, data)); }
    catch (error) { announce(error.message, true); }
    finally { busy = false; document.querySelectorAll("button, input, select").forEach((control) => { control.disabled = false; }); updateActions(); }
  }
  q("reload").onclick = () => {
    if (busy || pendingCount(pending)) { announce("Apply or discard the pending labels before reloading.", true); return; }
    if (dirty && !window.confirm("Discard the unsaved edits on this page and reload the saved review?")) return;
    operate("/api/review", undefined, (value) => { accept(value); announce("Saved review loaded. Originals and AI groups are unchanged."); });
  };
  q("select-all").onclick = () => { if (!canEdit()) return; selection = new Set(snapshot.assets.map((a) => a.asset_id)); updateSelection(); };
  q("clear-selection").onclick = () => { if (!canEdit()) return; selection.clear(); updateSelection(); };
  q("assignment-target").onchange = () => {
    q("assignment-title").value = draft.objects.find((o) => o.object_id === q("assignment-target").value)?.title || ""; updateSelection();
  };
  q("assignment-title").oninput = updateSelection;
  q("assign").onclick = () => {
    if (!canEdit() || !selection.size) return;
    const id = q("assignment-target").value === "new" ? "object-" + crypto.randomUUID() : q("assignment-target").value;
    try {
      const hadPending = pendingCount(pending) > 0;
      updated(assignPhotos(draft, [...selection], id, q("assignment-title").value)); render(); rebuildAssignmentTargets(id);
      if (!hadPending || pendingCount(pending)) q("batch-status").textContent = "Assigned " + selection.size + " photos. Save the draft when ready.";
    } catch (error) { announce(error.message, true); }
  };
  for (const [key, text] of [["stele", "Stele faces"], ["calligraphy", "Work positions"]]) {
    const control = button(text, () => { if (busy || conflict) return; mode = key; renderInspector(); }); control.dataset.mode = key;
    q("inspector-mode").append(control);
  }
  q("apply-inspector").onclick = () => {
    if (!canLabel() || !pendingCount(pending)) return;
    try {
      const next = applyInspectorPatch(draft, selection, pending, pendingContext);
      discardPending("Labels applied to " + selection.size + " photos. Save the local draft when ready."); updated(next); render();
    } catch (error) { announce(error.message, true); }
  };
  q("discard-inspector").onclick = () => { if (busy || conflict) return; discardPending("Pending labels discarded. Saved and applied labels are unchanged."); updateActions(); };
  q("reviewer").oninput = updateActions;
  q("save").onclick = () => {
    if (busy || conflict || !saveAllowed(snapshot, dirty, pendingCount(pending) > 0)) return;
    operate("/api/save", { expected_revision: snapshot.revision, draft }, (value) => { accept(value); announce("Draft saved locally. No human decision was recorded."); });
  };
  q("confirm").onclick = () => {
    if (busy || conflict || !confirmationAllowed(snapshot, draft, dirty, q("reviewer").value, pendingCount(pending) > 0) || snapshot.confirmed_revision === snapshot.revision) return;
    operate("/api/confirm", { expected_revision: snapshot.revision, reviewer: q("reviewer").value.trim() }, (value) => { accept(value); announce("The saved revision has a separate named human confirmation."); });
  };
  q("export").onclick = () => {
    if (busy || conflict || pendingCount(pending) || dirty || snapshot?.confirmed_revision !== snapshot?.revision) return;
    operate("/api/export", { expected_revision: snapshot.revision }, (value) => {
      q("export-result").replaceChildren(node("span", "Confirmed metadata exported. Originals are not included. "));
      if (typeof value.download_url === "string" && value.download_url.startsWith("/") && !value.download_url.startsWith("//")) {
        const link = node("a", "Download metadata dataset"); link.href = value.download_url; link.setAttribute("download", ""); q("export-result").append(link);
      }
      if (value.summary || value.counts) q("export-result").append(node("p", JSON.stringify(value.summary || value.counts)));
      announce("Export completed locally. Nothing was uploaded or published.");
    });
  };
  window.addEventListener("beforeunload", (event) => { if (dirty || pendingCount(pending)) { event.preventDefault(); event.returnValue = ""; } });
  operate("/api/review", undefined, (value) => { accept(value); announce("Select photos, assign a named object, then label them in the side panel."); });
})();
