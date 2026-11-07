/*
 * Atelier prosopo-gw: place validation screen (design § 7).
 *
 * Plain JavaScript, no build step. The page talks to the local API of the
 * same server (same origin). Every value shown comes from the user's .gw
 * file, so the page never builds HTML from strings: nodes are created with
 * document.createElement and filled with textContent. Cluster ids go in URL
 * paths through encodeURIComponent; writings travel only in JSON bodies.
 */
"use strict";

(() => {
  // -- labels (French UI) ----------------------------------------------------

  const FIELDS = [
    ["commune", "Commune"],
    ["insee_code", "Code INSEE"],
    ["postal_code", "Code postal"],
    ["department", "Département"],
    ["region", "Région"],
    ["country", "Pays"],
    ["former_name", "Ancien nom"],
  ];
  /** Fields always shown; the others only when the place or proposal has them. */
  const ALWAYS_SHOWN = new Set([
    "commune", "insee_code", "department", "region", "country", "former_name",
  ]);
  const STATE_LABELS = {
    todo: "à traiter",
    validated: "validé",
    rejected: "rejeté",
    already_decided: "déjà décidé",
  };
  const STATE_ICONS = { todo: "○", validated: "✓", rejected: "✕", already_decided: "●" };
  const CONFIDENCE_LABELS = { high: "haute", medium: "moyenne", low: "faible" };
  const ORIGIN_LABELS = {
    rule: "règle", manual: "manuel", reference: "référentiel", llm: "LLM",
  };
  const DECIDED_LABELS = { validated: "déjà validée", rejected: "déjà rejetée" };
  const FILTERS = [
    ["todo", "À traiter"],
    ["validated", "Validés"],
    ["rejected", "Rejetés"],
    ["already_decided", "Déjà décidés"],
    ["all", "Tous"],
  ];
  const UNDO_LABELS = {
    validate: "validation",
    split: "sortie d'écritures",
    reject: "rejet",
    correct: "correction d'un champ",
    import: "import du référentiel",
    resolve: "résolution d'un conflit",
  };
  const FLASH_MS = 1700;
  const INFO_MS = 6000;

  // -- state -------------------------------------------------------------------

  const state = {
    project: null, // GET /api/project
    clusters: [], // GET /api/clusters, in queue order
    filter: "todo",
    currentId: null,
    detail: null, // GET /api/clusters/{id}
    unchecked: new Set(), // writings of the open cluster to take out
    drafts: {}, // field kind -> value typed in the form
    notice: null, // {fromId, toId, writings, label} after a split
    flashId: null, // cluster to flash in the queue
    occurrences: null, // null: hidden; else Map writing -> list or Error
    busy: false,
    history: [], // cluster open before each action, to come back on undo
  };

  const $ = (id) => document.getElementById(id);
  let messageTimer = null;
  let flashTimer = null;

  // -- DOM helpers -------------------------------------------------------------

  /**
   * Create an element. `props`: `class`, `text` (textContent), `on<event>`
   * (listener), `dataset`, DOM properties (`checked`, `disabled`, `value`,
   * `hidden`…) or attributes. Children: nodes or strings (text nodes).
   */
  function el(tag, props, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") node.className = value;
      else if (key === "text") node.textContent = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
      else if (key in node && typeof value !== "string") node[key] = value;
      else if (key === "value") node.value = value;
      else node.setAttribute(key, value);
    }
    append(node, children);
    return node;
  }

  function append(node, children) {
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.append(typeof child === "string" ? document.createTextNode(child) : child);
    }
    return node;
  }

  function plural(n, one, many) {
    return `${n} ${n > 1 ? many : one}`;
  }

  // -- API -----------------------------------------------------------------------

  class ApiError extends Error {}

  /** Call the local API; throw ApiError carrying the server's French `detail`. */
  async function api(method, path, body) {
    const options = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, options);
    } catch (_error) {
      throw new ApiError(
        "Le serveur de l'atelier ne répond pas. Est-il toujours lancé ?",
      );
    }
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (_error) {
        data = null;
      }
    }
    if (!response.ok) {
      const detail = data && typeof data.detail === "string"
        ? data.detail
        : `Erreur ${response.status} du serveur.`;
      throw new ApiError(detail);
    }
    return data;
  }

  function clusterPath(id, action) {
    const base = `/api/clusters/${encodeURIComponent(id)}`;
    return action ? `${base}/${action}` : base;
  }

  // -- messages ------------------------------------------------------------------

  function showMessage(text, kind) {
    const box = $("message");
    $("message-text").textContent = text;
    box.classList.toggle("error", kind === "error");
    box.setAttribute("role", kind === "error" ? "alert" : "status");
    box.hidden = false;
    clearTimeout(messageTimer);
    if (kind !== "error") messageTimer = setTimeout(hideMessage, INFO_MS);
  }

  function hideMessage() {
    clearTimeout(messageTimer);
    $("message").hidden = true;
  }

  // -- queue ---------------------------------------------------------------------

  function clusterById(id) {
    return state.clusters.find((c) => c.id === id) || null;
  }

  /** Clusters shown by the filter; the open one stays visible whatever its state. */
  function visibleClusters() {
    return state.clusters.filter(
      (c) => state.filter === "all" || c.state === state.filter || c.id === state.currentId,
    );
  }

  function renderHeader() {
    const total = state.clusters.length;
    const treated = state.clusters.filter((c) => c.state !== "todo").length;
    $("counter").textContent = `${plural(total, "cluster", "clusters")} · ${plural(treated, "traité", "traités")}`;
    $("progress").style.width = total ? `${(100 * treated) / total}%` : "0";
    const project = state.project;
    $("gw-name").textContent = project ? project.gw_name : "";
    $("gw-changed").hidden = !(project && project.gw_changed);
    $("gw-changed-name").textContent = project ? project.gw_name : "";
    $("undo-button").disabled = state.busy;
  }

  function renderFilters() {
    const box = $("filters");
    box.replaceChildren(
      ...FILTERS.map(([key, label]) => {
        const count = key === "all"
          ? state.clusters.length
          : state.clusters.filter((c) => c.state === key).length;
        return el("button", {
          type: "button",
          "aria-pressed": String(state.filter === key),
          onclick: () => setFilter(key),
          text: `${label} (${count})`,
        });
      }),
    );
  }

  function renderQueue() {
    const list = $("queue-list");
    const items = visibleClusters();
    if (!items.length) {
      list.replaceChildren(el("li", { class: "queue-empty", text: "Aucun lieu dans ce filtre." }));
      return;
    }
    list.setAttribute("role", "listbox");
    list.replaceChildren(
      ...items.map((c) => {
        const classes = ["queue-item", `state-${c.state}`];
        if (c.parent_id) classes.push("child");
        if (c.id === state.flashId) classes.push("flash");
        return el(
          "li",
          {
            class: classes.join(" "),
            role: "option",
            "aria-selected": String(c.id === state.currentId),
            title: `${c.label} · ${STATE_LABELS[c.state]} · ${plural(c.writing_count, "écriture", "écritures")}`,
            onclick: () => run(() => openCluster(c.id)),
          },
          c.parent_id ? el("span", { "aria-hidden": "true", text: "↳" }) : null,
          el("span", { class: "state-icon", "aria-label": STATE_LABELS[c.state], text: STATE_ICONS[c.state] }),
          el("span", { class: "label", text: c.label }),
          el("span", { class: `tag ${c.confidence}`, text: CONFIDENCE_LABELS[c.confidence] }),
          el("span", { class: "count", title: "occurrences", text: String(c.occurrences) }),
        );
      }),
    );
    const selected = list.querySelector('[aria-selected="true"]');
    if (selected) selected.scrollIntoView({ block: "nearest" });
  }

  function renderAll() {
    renderHeader();
    renderFilters();
    renderQueue();
    renderDetail();
  }

  // -- detail --------------------------------------------------------------------

  function shownFields(detail) {
    return FIELDS.filter(
      ([kind]) => ALWAYS_SHOWN.has(kind) || kind in detail.proposal || kind in detail.origins,
    );
  }

  function renderNotice(detail) {
    const notice = state.notice;
    if (!notice || notice.fromId !== detail.id) return null;
    return el(
      "div",
      { class: "notice", role: "status" },
      el("span", {
        text: `✂ ${plural(notice.writings.length, "écriture sortie", "écritures sorties")} de ce lieu :`,
      }),
      notice.writings.map((w) => el("code", { text: w })),
      el("span", { text: "→ nouveau lieu" }),
      el("strong", { text: `« ${notice.label} »` }),
      el("span", { text: ", placé juste en dessous dans la file, à traiter." }),
      el("button", {
        type: "button",
        text: "Ouvrir le nouveau lieu",
        onclick: () => run(() => openCluster(notice.toId)),
      }),
    );
  }

  function renderForm(detail) {
    const parent = detail.parent_id ? clusterById(detail.parent_id) : null;
    const total = detail.writings.length;
    return el(
      "div",
      { class: "card" },
      el(
        "h2",
        null,
        el("span", { text: detail.label || "Lieu non identifié" }),
        el("span", { class: `state ${detail.state}`, text: STATE_LABELS[detail.state] }),
      ),
      el("div", {
        class: "sub",
        text: `${plural(total, "écriture", "écritures")} · ${plural(detail.occurrences, "occurrence", "occurrences")} · confiance ${CONFIDENCE_LABELS[detail.confidence]}`,
      }),
      parent
        ? el("div", { class: "sub", text: `Sorti du lieu « ${parent.label} ».` })
        : null,
      el(
        "div",
        { class: "fields" },
        shownFields(detail).map(([kind, label]) => {
          const id = `field-${kind}`;
          const origin = detail.origins[kind];
          return el(
            "div",
            null,
            el(
              "label",
              { for: id },
              label,
              origin ? el("span", { class: "origin", text: `(${ORIGIN_LABELS[origin] || origin})` }) : null,
            ),
            el("input", {
              id,
              type: "text",
              autocomplete: "off",
              spellcheck: "false",
              placeholder: "vide = supprimer",
              value: state.drafts[kind] ?? "",
              oninput: (event) => {
                state.drafts[kind] = event.target.value;
              },
            }),
          );
        }),
      ),
      el("p", {
        class: "sub",
        text: "Forme retenue : modifiez les champs puis validez. Un champ vidé est retiré du lieu.",
      }),
    );
  }

  function renderComplements(detail) {
    if (!detail.complements.length) return null;
    return el(
      "div",
      { class: "card" },
      el("h3", {
        text: "Compléments, gardés à part (adresse ou établissement, pas une variante de la commune)",
      }),
      el(
        "ul",
        { class: "complements" },
        detail.complements.map((c) =>
          el("li", null, el("code", { text: c.text }), ` (${plural(c.occurrences, "occurrence", "occurrences")})`),
        ),
      ),
    );
  }

  function renderWritings(detail) {
    const rows = detail.writings.map((w) => {
      const row = el(
        "tr",
        { class: state.unchecked.has(w.text) ? "moving" : null },
        el(
          "td",
          null,
          el("input", {
            type: "checkbox",
            checked: !state.unchecked.has(w.text),
            "aria-label": `Garder « ${w.text} » dans ce lieu`,
            onchange: (event) => {
              if (event.target.checked) state.unchecked.delete(w.text);
              else state.unchecked.add(w.text);
              row.classList.toggle("moving", !event.target.checked);
              updateSplitButton();
            },
          }),
        ),
        el("td", null, el("code", { text: w.text })),
        el("td", { class: "num", text: String(w.occurrences) }),
        el(
          "td",
          { class: "sub" },
          w.hint,
          w.decided ? el("span", { class: `state ${w.decided}`, text: DECIDED_LABELS[w.decided] }) : null,
        ),
      );
      return row;
    });
    return el(
      "div",
      { class: "card" },
      el(
        "table",
        null,
        el(
          "thead",
          null,
          el(
            "tr",
            null,
            el("th", { title: "Cochée : l'écriture désigne ce lieu", text: "✓" }),
            el("th", { text: "Écriture d'origine" }),
            el("th", { class: "num", text: "Occ." }),
            el("th", { text: "Indice de rattachement" }),
          ),
        ),
        el("tbody", null, rows),
      ),
      renderActions(),
      el(
        "div",
        { class: "keys" },
        "Décochez les écritures qui ne désignent pas ce lieu, puis « Sortir » : elles forment un nouveau lieu à traiter. Clavier : ",
        el("kbd", { text: "V" }), " valider · ",
        el("kbd", { text: "S" }), " sortir · ",
        el("kbd", { text: "R" }), " rejeter · ",
        el("kbd", { text: "O" }), " occurrences · ",
        el("kbd", { text: "↑" }), "/", el("kbd", { text: "↓" }), " naviguer · ",
        el("kbd", { text: "Ctrl+Z" }), " annuler.",
      ),
    );
  }

  function renderActions() {
    return el(
      "div",
      { class: "actions" },
      el("button", { type: "button", class: "primary", text: "Valider", title: "Valider (V)", onclick: () => run(validate) }),
      el("button", { type: "button", id: "split-button", title: "Sortir (S)", onclick: () => run(splitOut) }),
      el("button", { type: "button", class: "danger", text: "Rejeter", title: "Pas un lieu exploitable (R)", onclick: () => run(reject) }),
      el("button", {
        type: "button",
        text: state.occurrences ? "Masquer les occurrences" : "Voir les occurrences",
        title: "Occurrences (O)",
        onclick: () => run(toggleOccurrences),
      }),
      el("button", { type: "button", text: "Annuler", title: "Annuler la dernière action (Ctrl+Z)", onclick: () => run(undo) }),
    );
  }

  function updateSplitButton() {
    const button = $("split-button");
    if (!button) return;
    const n = state.unchecked.size;
    button.textContent = `✂ Sortir les décochées vers un nouveau lieu (${n})`;
    button.disabled = n === 0;
    button.title = n === 0 ? "Décochez d'abord les écritures à sortir" : "Sortir (S)";
  }

  function renderOccurrences(detail) {
    if (!state.occurrences) return null;
    const rows = [];
    for (const w of detail.writings) {
      const found = state.occurrences.get(w.text);
      if (found instanceof Error) {
        rows.push(el("tr", null, el("td", null, el("code", { text: w.text })), el("td", { colspan: "4", text: found.message })));
        continue;
      }
      for (const o of found || []) {
        rows.push(
          el(
            "tr",
            null,
            el("td", null, el("code", { text: w.text })),
            el("td", { text: o.label || "—" }),
            el("td", { text: o.kind_label }),
            el("td", { text: o.date || "" }),
            el("td", null, o.complement ? el("code", { text: o.complement }) : ""),
          ),
        );
      }
    }
    return el(
      "div",
      { class: "card" },
      el("h3", { text: "Occurrences : personnes et événements concernés" }),
      el(
        "table",
        null,
        el(
          "thead",
          null,
          el(
            "tr",
            null,
            el("th", { text: "Écriture" }),
            el("th", { text: "Personne ou famille" }),
            el("th", { text: "Événement" }),
            el("th", { text: "Date" }),
            el("th", { text: "Complément" }),
          ),
        ),
        el("tbody", null, rows),
      ),
    );
  }

  function renderDetail() {
    const section = $("detail");
    const detail = state.detail;
    if (!detail) {
      section.replaceChildren(el("p", { class: "empty", text: "Aucun lieu dans ce filtre." }));
      return;
    }
    section.replaceChildren(
      ...[
        renderNotice(detail),
        renderForm(detail),
        renderComplements(detail),
        renderWritings(detail),
        renderOccurrences(detail),
      ].filter(Boolean),
    );
    updateSplitButton();
  }

  // -- loading -------------------------------------------------------------------

  async function refresh() {
    const [project, clusters] = await Promise.all([
      api("GET", "/api/project"),
      api("GET", "/api/clusters"),
    ]);
    state.project = project;
    state.clusters = clusters;
  }

  /** Open a cluster; `keepNotice` keeps the banner of a split just made. */
  async function openCluster(id, keepNotice) {
    if (!keepNotice) state.notice = null;
    state.unchecked = new Set();
    state.occurrences = null;
    state.currentId = id;
    state.detail = null;
    try {
      if (id !== null) {
        state.detail = await api("GET", clusterPath(id));
        state.drafts = { ...state.detail.proposal };
      }
    } finally {
      renderAll();
    }
  }

  function firstVisible() {
    const items = state.clusters.filter((c) => state.filter === "all" || c.state === state.filter);
    return items.length ? items[0].id : null;
  }

  /** The cluster after the open one in the queue, to move on after a decision. */
  function nextAfterCurrent() {
    const items = visibleClusters();
    const index = items.findIndex((c) => c.id === state.currentId);
    const rest = items.slice(index + 1).concat(items.slice(0, Math.max(index, 0)));
    const next = rest.find((c) => state.filter === "all" || c.state === state.filter);
    return next ? next.id : null;
  }

  function setFilter(key) {
    state.filter = key;
    const current = clusterById(state.currentId);
    if (current && (key === "all" || current.state === key)) {
      renderAll();
      return;
    }
    run(() => openCluster(firstVisible()));
  }

  // -- actions -------------------------------------------------------------------

  /** Run one action at a time and show its error, if any. */
  async function run(action) {
    if (state.busy) return;
    state.busy = true;
    renderHeader();
    try {
      await action();
    } catch (error) {
      showMessage(error.message || String(error), "error");
    } finally {
      state.busy = false;
      renderHeader();
    }
  }

  function flash(id) {
    state.flashId = id;
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => {
      state.flashId = null;
      const item = document.querySelector(".queue-item.flash");
      if (item) item.classList.remove("flash");
    }, FLASH_MS);
  }

  async function validate() {
    const detail = state.detail;
    if (!detail) return;
    const fields = {};
    for (const [kind] of shownFields(detail)) fields[kind] = state.drafts[kind] ?? "";
    const writings = detail.writings.map((w) => w.text);
    const checked = writings.filter((w) => !state.unchecked.has(w));
    const taken = writings.filter((w) => state.unchecked.has(w));
    const next = nextAfterCurrent();
    const result = await api("POST", clusterPath(detail.id, "validate"), { fields, checked });
    state.history.push(detail.id);
    const placeCluster = `place:${result.place_id}`;
    await refresh();
    const label = detail.label || "Lieu";
    if (result.split) {
      // Stay on the place just validated and say where the writings went.
      state.notice = { fromId: placeCluster, toId: result.split.id, writings: taken, label: result.split.label };
      flash(result.split.id);
      await openCluster(clusterById(placeCluster) ? placeCluster : detail.id, true);
      showMessage(`« ${label} » validé.`, "info");
    } else {
      await openCluster(next && clusterById(next) ? next : placeCluster);
      showMessage(`« ${label} » validé.`, "info");
    }
  }

  async function splitOut() {
    const detail = state.detail;
    if (!detail || state.unchecked.size === 0) return;
    const writings = detail.writings.map((w) => w.text).filter((w) => state.unchecked.has(w));
    const created = await api("POST", clusterPath(detail.id, "split"), { writings });
    state.history.push(detail.id);
    await refresh();
    const origin = clusterById(detail.id) ? detail.id : created.parent_id;
    state.notice = { fromId: origin, toId: created.id, writings, label: created.label };
    flash(created.id);
    await openCluster(origin, true);
  }

  async function reject() {
    const detail = state.detail;
    if (!detail) return;
    const next = nextAfterCurrent();
    await api("POST", clusterPath(detail.id, "reject"));
    state.history.push(detail.id);
    await refresh();
    await openCluster(next && clusterById(next) ? next : detail.id);
    showMessage(`« ${detail.label} » rejeté : pas un lieu exploitable.`, "info");
  }

  async function toggleOccurrences() {
    const detail = state.detail;
    if (!detail) return;
    if (state.occurrences) {
      state.occurrences = null;
      renderDetail();
      return;
    }
    const entries = await Promise.all(
      detail.writings.map(async (w) => {
        try {
          return [w.text, await api("POST", "/api/occurrences", { writing: w.text })];
        } catch (error) {
          return [w.text, error];
        }
      }),
    );
    if (state.detail !== detail) return; // another cluster was opened meanwhile
    state.occurrences = new Map(entries);
    renderDetail();
  }

  async function undo() {
    const result = await api("POST", "/api/undo");
    const before = state.history.pop();
    await refresh();
    let target = null;
    for (const id of [before, state.currentId]) {
      if (id && clusterById(id)) {
        target = id;
        break;
      }
    }
    await openCluster(target || firstVisible());
    showMessage(`Action annulée : ${UNDO_LABELS[result.action] || result.action}.`, "info");
  }

  async function reloadGw() {
    await api("POST", "/api/project/reload");
    await refresh();
    const id = clusterById(state.currentId) ? state.currentId : firstVisible();
    await openCluster(id);
    showMessage("Fichier relu ; les décisions déjà prises sont conservées.", "info");
  }

  function move(step) {
    const items = visibleClusters();
    if (!items.length) return;
    const index = items.findIndex((c) => c.id === state.currentId);
    const target = index < 0 ? 0 : Math.min(Math.max(index + step, 0), items.length - 1);
    if (items[target].id !== state.currentId) run(() => openCluster(items[target].id));
  }

  // -- keyboard ------------------------------------------------------------------

  /** True when the key goes to a text field: shortcuts and Ctrl+Z stay the browser's. */
  function isTyping(target) {
    if (!target || !(target instanceof Element)) return false;
    if (target.isContentEditable) return true;
    if (target.tagName === "TEXTAREA" || target.tagName === "SELECT") return true;
    if (target.tagName === "INPUT") {
      return !["checkbox", "radio", "button", "submit", "reset"].includes(target.type);
    }
    return false;
  }

  function onKeyDown(event) {
    if (isTyping(event.target)) {
      if (event.key === "Escape") event.target.blur();
      return;
    }
    const key = event.key;
    if ((event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && key.toLowerCase() === "z") {
      event.preventDefault();
      run(undo);
      return;
    }
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (key === "ArrowDown" || key === "ArrowUp") {
      event.preventDefault();
      move(key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (event.repeat) return;
    const actions = { v: validate, s: splitOut, r: reject, o: toggleOccurrences };
    const action = actions[key.toLowerCase()];
    if (action && state.detail) {
      event.preventDefault();
      run(action);
    }
  }

  // -- start -----------------------------------------------------------------------

  function start() {
    $("undo-button").addEventListener("click", () => run(undo));
    $("reload-button").addEventListener("click", () => run(reloadGw));
    $("message-close").addEventListener("click", hideMessage);
    document.addEventListener("keydown", onKeyDown);
    run(async () => {
      await refresh();
      if (!state.clusters.some((c) => c.state === "todo") && state.clusters.length) {
        state.filter = "all";
      }
      await openCluster(firstVisible());
    });
  }

  start();
})();
