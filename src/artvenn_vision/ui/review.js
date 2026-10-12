/* Local drafts and human decisions; no inference, upload or publication. */
(() => {
  "use strict";
  const copy = (value) => JSON.parse(JSON.stringify(value));
  const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  const uncertainty = new Set(["unknown", "not_applicable"]);
  const roleNames = { overview: "Overall view", detail: "Detail", label: "Exhibition label", context: "Environment", unspecified: "Unspecified" };
  const axisNames = {
    object_kind: "Object type", representation: "Image source", capture_method: "Acquisition",
    coverage: "Capture coverage", surfaces: "Stele surfaces", side_reference: "Side reference",
    parts: "Stele parts", work_format: "Calligraphy format", positions: "Calligraphy position",
    content: "Visible content", version_label: "Rubbing / version name", position_index: "Page / capture number", notes: "Evidence and uncertainty",
  };
  const valueNames = {
    inscription: "Inscription", calligraphy: "Calligraphy", unknown: "Unknown", not_applicable: "Not applicable",
    stone: "Original stone", ink_original: "Original ink", rubbing: "Rubbing", facsimile: "Facsimile / copy", photo: "Photograph", scan: "Scan",
    whole_object: "Whole object", whole_surface_page: "Whole surface / page", detail: "Detail", context: "Environment", label: "Exhibition label",
    front: "Front (stele yang)", back: "Back (stele yin)", side_unspecified: "Side, unspecified", left: "Left side", right: "Right side", other: "Other",
    facing_front: "Left / right when facing the stele front", head: "Stele head", body: "Stele body", base: "Stele base",
    handscroll: "Handscroll", album: "Album", folded_book: "Folded book", hanging_scroll: "Hanging scroll",
    main_work: "Main work", frontispiece: "Frontispiece", tail: "Tail", cover_mount: "Cover / mounting", leaf_page: "Leaf / page",
    main_text: "Main text", stele_title: "Stele forehead text", title: "Title text", colophon: "Colophon", title_slip: "Title slip", signature: "Inscription / signature", seal: "Seal", ornament: "Ornament", damage: "Damage",
  };
  const name = (value) => valueNames[value] || String(value).replaceAll("_", " ");

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
    // Source proposals and prior saved revisions retain emptied source objects.
    // This draft contains only the named destinations of its current photos.
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
  function confirmationAllowed(snapshot, draft, dirty, reviewer) {
    return !!snapshot && snapshot.revision > 0 && !dirty && !!reviewer.trim() &&
      draft.objects.length > 0 && draft.objects.every((object) => object.title.trim() && object.asset_ids.length) &&
      Object.values(draft.photos).every((photo) => photo.object_id && draft.objects.some((object) => object.object_id === photo.object_id && object.title.trim()));
  }
  function saveAllowed(snapshot, dirty) {
    return !!snapshot && (snapshot.revision === 0 || dirty);
  }
  const helpers = { sourceGroups, toggleSelection, assignPhotos, editSelected, patchValue, confirmationAllowed, saveAllowed };
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
  let bulkValue = null;
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
  function selectControl(values, value, change) {
    const control = node("select");
    for (const [key, text] of values) {
      const option = node("option", text);
      option.value = key ?? "";
      control.append(option);
    }
    control.value = value ?? "";
    control.onchange = () => change(control.value);
    return control;
  }
  function announce(text, error = false) {
    q("notice").textContent = text;
    q("notice").classList.toggle("error", error);
  }
  function updated(next) {
    if (same(next, draft)) return;
    draft = next;
    dirty = true;
    q("export-result").replaceChildren();
    updateActions();
  }
  function updateActions() {
    const ready = !!snapshot && !busy;
    q("save").disabled = !ready || conflict || !saveAllowed(snapshot, dirty);
    q("confirm").disabled = !ready || conflict || !confirmationAllowed(snapshot, draft, dirty, q("reviewer").value) || snapshot.confirmed_revision === snapshot.revision;
    q("export").disabled = !ready || conflict || dirty || snapshot.confirmed_revision !== snapshot.revision;
    q("revision-status").textContent = snapshot ? "Saved revision " + snapshot.revision + " · " + (dirty ? "Unsaved changes" : snapshot.confirmed_revision === snapshot.revision ? "Human confirmed" : "Draft, not confirmed") : "";
    q("confirmation-help").textContent = dirty ? "Save these edits before confirming. Confirmation uses the saved revision." : snapshot?.confirmed_revision === snapshot?.revision && snapshot ? "The saved revision is confirmed. Further edits create a new draft." : "Assign every photo to a named object and enter your reviewer name before confirming.";
    updateSelection();
  }
  function updateSelection() {
    q("selected-count").textContent = selection.size + " unique photos selected";
    q("select-all").disabled = busy || !snapshot;
    q("clear-selection").disabled = busy || !snapshot || !selection.size;
    for (const [id, entries] of cards)
      for (const { tile, check } of entries) { check.checked = selection.has(id); tile.classList.toggle("selected", check.checked); }
    for (const { check, ids } of groupChecks) {
      const count = ids.filter((id) => selection.has(id)).length;
      check.checked = count === ids.length;
      check.indeterminate = count > 0 && count < ids.length;
    }
    q("assign").disabled = busy || !selection.size || !q("assignment-title").value.trim();
    q("apply-role").disabled = busy || !selection.size;
    const operation = q("bulk-operation").value;
    q("apply-label").disabled = busy || !selection.size || !q("bulk-axis").value || operation === "unchanged" || (operation !== "clear" && (bulkValue === null || bulkValue === "" || (Array.isArray(bulkValue) && !bulkValue.length)));
    q("mixed-status").textContent = "";
    if (draft && selection.size && q("bulk-axis").value) {
      const values = [...selection].map((id) => draft.photos[id].labels[q("bulk-axis").value]);
      q("mixed-status").textContent = values.some((value) => !same(value, values[0])) ? "Selected photos have different current values." : "Selected photos have the same current value.";
    }
  }
  function labelInput(key, definition, value, change) {
    if (definition.type === "array") {
      const box = node("div");
      box.className = "annotation-options";
      const checks = [];
      for (const item of definition.items.enum) {
        const check = node("input"); check.type = "checkbox"; check.value = item;
        check.checked = (value || []).includes(item);
        check.setAttribute("aria-label", axisNames[key] + ": " + name(item));
        check.onchange = () => {
          let values = checks.filter((c) => c.checked).map((c) => c.value);
          if (check.checked && uncertainty.has(item)) values = [item];
          else if (values.length > 1) values = values.filter((v) => !uncertainty.has(v));
          for (const c of checks) c.checked = values.includes(c.value);
          change(values.sort());
        };
        checks.push(check); box.append(label(name(item), check));
      }
      return box;
    }
    if (definition.enum) return selectControl(definition.enum.map((value) => [value, value === null ? "Not annotated / clear" : name(value)]), value, (value) => change(value || null));
    const control = node("input");
    control.type = key === "position_index" ? "number" : "text";
    if (control.type === "number") control.min = "1";
    else control.maxLength = definition.maxLength || 1000;
    control.value = value ?? "";
    control.onchange = () => change(control.value === "" ? null : control.type === "number" ? Number(control.value) : control.value);
    return control;
  }
  function buildPhoto(asset) {
    const id = asset.asset_id;
    const tile = node("article"); tile.className = "photo-card";
    const image = node("img"); image.src = "/previews/" + encodeURIComponent(id) + ".jpg"; image.alt = "Prepared photo " + id; image.loading = "lazy";
    const check = node("input"); check.type = "checkbox"; check.setAttribute("aria-label", "Select photo " + id);
    check.onchange = () => { selection = toggleSelection(selection, [id], check.checked); updateSelection(); };
    const selectionLabel = label("Select this photo", check); selectionLabel.className = "photo-selection";
    tile.append(image, node("p", id), selectionLabel); tile.children[1].className = "photo-id";
    const purpose = selectControl(Object.entries(roleNames), draft.photos[id].role, (value) => { updated(editSelected(draft, [id], { role: value })); renderPhotoCopies(id); });
    tile.append(label("Photo purpose", purpose));
    const object = selectControl([["", "Not assigned"], ...draft.objects.map((o) => [o.object_id, o.title])], draft.photos[id].object_id, (value) => {
      const next = copy(draft); next.photos[id].object_id = value || null; updated(synchronizeMemberships(next)); render();
    });
    tile.append(label("Assigned object", object));
    const details = node("details"); details.className = "annotation-panel";
    const values = draft.photos[id].labels;
    const present = Object.entries(values).flatMap(([key, value]) => Array.isArray(value) ? value.map(name) : value === null ? [] : [typeof value === "string" && valueNames[value] ? name(value) : axisNames[key]]);
    details.append(node("summary", "Professional labels · " + (present.length ? present.join(", ") : "Not annotated")));
    for (const [key, definition] of Object.entries(taxonomy)) {
      const control = labelInput(key, definition, values[key], (value) => { updated(editSelected(draft, [id], { axis: key, operation: "set", value, multi: definition.type === "array" })); refreshLabelSummary(id); });
      // Each checkbox owns its label. An outer label would nest labels and can
      // make clicks select the wrong checkbox in a multi-value dimension.
      const field = definition.type === "array" ? node("div") : label(axisNames[key] || name(key), control);
      if (definition.type === "array") field.append(node("p", axisNames[key] || name(key)), control);
      field.className = "annotation-field"; field.dataset.axis = key;
      const empty = Array.isArray(values[key]) ? !values[key].length : !values[key];
      field.hidden = empty && ((values.object_kind === "calligraphy" && ["surfaces", "parts", "side_reference"].includes(key)) || (values.object_kind === "inscription" && ["work_format", "positions", "position_index"].includes(key)));
      if (key === "positions") {
        const relevant = {
          handscroll: ["main_work", "frontispiece", "tail", "cover_mount"],
          album: ["main_work", "leaf_page", "cover_mount"],
          folded_book: ["main_work", "leaf_page", "cover_mount"],
          hanging_scroll: ["main_work", "cover_mount"],
        }[values.work_format];
        for (const option of control.children) {
          const check = option.lastElementChild;
          if (check) option.hidden = !!relevant && ![...relevant, "other", "unknown", "not_applicable"].includes(check.value) && !check.checked;
        }
      }
      details.append(field);
    }
    details.append(node("p", "Sides use the view facing the stele front. Unknown does not mean absent. Labels describe the image; they do not align regions or train a model.")); details.lastChild.className = "annotation-hint";
    tile.append(details);
    if (!cards.has(id)) cards.set(id, []);
    cards.get(id).push({ tile, check });
    return tile;
  }
  function refreshLabelSummary(id) {
    // Recreate repeated appearances from one canonical photo draft, retaining open panels.
    renderPhotoCopies(id);
  }
  function renderPhotoCopies(id) {
    const previous = cards.get(id) || [];
    cards.set(id, []);
    const asset = snapshot.assets.find((a) => a.asset_id === id);
    for (const { tile } of previous) {
      const opened = tile.querySelector("details").open;
      const next = buildPhoto(asset); next.querySelector("details").open = opened;
      tile.replaceWith(next);
    }
    updateSelection();
  }
  function rebuildAssignmentTargets(value = q("assignment-target").value || "new") {
    const control = q("assignment-target"); control.replaceChildren();
    for (const [id, title] of [["new", "Create a named object"], ...draft.objects.map((o) => [o.object_id, o.title])]) {
      const option = node("option", title); option.value = id; control.append(option);
    }
    control.value = draft.objects.some((o) => o.object_id === value) ? value : "new";
  }
  function render() {
    const opened = new Set([...cards].filter(([, entries]) => entries.some(({ tile }) => tile.querySelector("details").open)).map(([id]) => id));
    cards.clear(); groupChecks.length = 0;
    const groups = sourceGroups(snapshot); const root = q("photo-groups"); root.replaceChildren();
    const processed = snapshot.processed_asset_ids?.length ?? new Set(groups.filter((g) => g.kind === "ai").flatMap((g) => g.asset_ids)).size;
    q("summary").textContent = snapshot.assets.length + " prepared photos · " + processed + " processed · " + (snapshot.assets.length - processed) + " unprocessed · all photos available below";
    for (const [index, group] of groups.entries()) {
      const section = node("section"); section.className = "source-group";
      const header = node("div"); header.className = "source-header";
      header.append(node("h2", (group.kind === "ai" ? "AI source group " + (index + 1) : "Photos without an AI group") + " · " + group.asset_ids.length + " photos"));
      const check = node("input"); check.type = "checkbox"; check.setAttribute("aria-label", "Select source group " + group.key);
      check.onchange = () => { selection = toggleSelection(selection, group.asset_ids, check.checked); updateSelection(); };
      groupChecks.push({ check, ids: group.asset_ids }); header.append(label("Select this source group", check));
      header.append(node("p", group.kind === "ai" ? "Source proposal preserved. Your object assignment and labels are saved separately." : "Prepared photos remain selectable even when inference is unfinished or did not return a group."));
      const grid = node("div"); grid.className = "photo-grid";
      for (const id of group.asset_ids) {
        const card = buildPhoto(snapshot.assets.find((a) => a.asset_id === id));
        card.querySelector("details").open = opened.has(id);
        grid.append(card);
      }
      section.append(header, grid); root.append(section);
    }
    rebuildAssignmentTargets(); updateActions();
  }
  function configureBulk() {
    bulkValue = null;
    const axis = q("bulk-axis").value; const operation = q("bulk-operation"); operation.replaceChildren(); q("bulk-value").replaceChildren();
    if (axis) {
      const definition = taxonomy[axis];
      for (const [key, text] of [["unchanged", "Leave unchanged"], ["set", "Replace this dimension"], ...(definition.type === "array" ? [["add", "Add selected labels"], ["remove", "Remove selected labels"]] : []), ["clear", "Clear this dimension"]]) {
        const option = node("option", text); option.value = key; operation.append(option);
      }
      q("bulk-value").append(labelInput(axis, definition, null, (value) => { bulkValue = value; updateSelection(); }));
    }
    updateSelection();
  }
  async function request(path, data) {
    const response = await fetch(path, data === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-ArtVenn-Session": config.csrfToken }, body: JSON.stringify(data) });
    const value = await response.json();
    if (!response.ok) {
      if (response.status === 409) conflict = true;
      const category = value.message || value.error_category || value.category || value.error || "Request failed";
      const reason = {
        annotation_side_reference_required: "Left or right side labels require the explicit facing-front side reference. Set Side reference for those photos first.",
        annotation_uncertainty_conflict: "Unknown or not applicable cannot be combined with a definite label in the same dimension.",
        annotation_value_invalid: "A professional label is invalid. Check the page number, text length and available choices.",
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
    dirty = false; conflict = false;
    const axis = q("bulk-axis"); const old = axis.value; axis.replaceChildren();
    const empty = node("option", "Choose a label dimension"); empty.value = ""; axis.append(empty);
    for (const key of Object.keys(taxonomy)) { const option = node("option", axisNames[key] || name(key)); option.value = key; axis.append(option); }
    if (Object.hasOwn(taxonomy, old)) axis.value = old;
    selection = new Set([...selection].filter((id) => Object.hasOwn(draft.photos, id)));
    configureBulk(); render();
  }
  async function operate(path, data, onSuccess) {
    if (busy) return;
    busy = true;
    document.querySelectorAll("button, input, select").forEach((control) => { control.disabled = true; });
    announce("Working locally…");
    try { onSuccess(await request(path, data)); }
    catch (error) { announce(error.message, true); }
    finally { busy = false; document.querySelectorAll("button, input, select").forEach((control) => { control.disabled = false; }); updateActions(); }
  }
  q("reload").onclick = () => {
    if (dirty && !window.confirm("Discard the unsaved edits on this page and reload the saved review?")) return;
    operate("/api/review", undefined, (value) => { accept(value); announce("Saved review loaded. Originals and AI groups are unchanged."); });
  };
  q("select-all").onclick = () => { selection = new Set(snapshot.assets.map((a) => a.asset_id)); updateSelection(); };
  q("clear-selection").onclick = () => { selection.clear(); updateSelection(); };
  q("assignment-target").onchange = () => {
    q("assignment-title").value = draft.objects.find((o) => o.object_id === q("assignment-target").value)?.title || ""; updateSelection();
  };
  q("assignment-title").oninput = updateSelection;
  q("assign").onclick = () => {
    const id = q("assignment-target").value === "new" ? "object-" + crypto.randomUUID() : q("assignment-target").value;
    try { updated(assignPhotos(draft, [...selection], id, q("assignment-title").value)); render(); rebuildAssignmentTargets(id); q("batch-status").textContent = "Assigned " + selection.size + " photos. Save the draft when ready."; }
    catch (error) { announce(error.message, true); }
  };
  for (const [key, text] of Object.entries(roleNames)) { const option = node("option", text); option.value = key; q("bulk-role").append(option); }
  q("apply-role").onclick = () => { updated(editSelected(draft, [...selection], { role: q("bulk-role").value })); for (const id of selection) renderPhotoCopies(id); q("batch-status").textContent = "Purpose updated for " + selection.size + " photos; other labels preserved."; };
  q("bulk-axis").onchange = configureBulk;
  q("bulk-operation").onchange = updateSelection;
  q("apply-label").onclick = () => {
    const axis = q("bulk-axis").value;
    updated(editSelected(draft, [...selection], { axis, operation: q("bulk-operation").value, value: bulkValue, multi: taxonomy[axis].type === "array" }));
    for (const id of selection) renderPhotoCopies(id);
    q("batch-status").textContent = "Edited " + axisNames[axis] + " for " + selection.size + " photos. Other dimensions remain unchanged; save and confirm separately.";
  };
  q("reviewer").oninput = updateActions;
  q("save").onclick = () => operate("/api/save", { expected_revision: snapshot.revision, draft }, (value) => { accept(value); announce("Draft saved locally. No human decision was recorded."); });
  q("confirm").onclick = () => operate("/api/confirm", { expected_revision: snapshot.revision, reviewer: q("reviewer").value.trim() }, (value) => { accept(value); announce("The saved revision has a separate named human confirmation."); });
  q("export").onclick = () => operate("/api/export", { expected_revision: snapshot.revision }, (value) => {
    q("export-result").replaceChildren(node("span", "Confirmed metadata exported. Originals are not included. "));
    if (typeof value.download_url === "string" && value.download_url.startsWith("/") && !value.download_url.startsWith("//")) {
      const link = node("a", "Download metadata dataset"); link.href = value.download_url; link.setAttribute("download", ""); q("export-result").append(link);
    }
    if (value.summary || value.counts) q("export-result").append(node("p", JSON.stringify(value.summary || value.counts)));
    announce("Export completed locally. Nothing was uploaded or published.");
  });
  operate("/api/review", undefined, (value) => { accept(value); announce("Choose photos below to assign an object or edit labels."); });
})();
