/*
 * Atelier prosopo-gw: place validation screen (design § 7; a place is a chain
 * of levels, edited row by row), data export
 * (§ 9) and the personal registry screen (§ 6.3: export, import, conflicts,
 * journal).
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
    ["historical_commune", "Commune historique"],
    ["historical_insee", "Code INSEE historique"],
  ];
  /** Fields always shown; the others only when the place has them. */
  const ALWAYS_SHOWN = new Set(["commune", "insee_code", "department", "region", "country"]);
  const STATE_LABELS = {
    todo: "à traiter",
    validated: "validé",
    rejected: "rejeté",
    already_decided: "déjà décidé",
  };
  const STATE_ICONS = { todo: "○", validated: "✓", rejected: "✕", already_decided: "●" };
  const CONFIDENCE_LABELS = { high: "haute", medium: "moyenne", low: "faible" };
  const ORIGIN_LABELS = {
    written: "écrit", rule: "règle", manual: "manuel", insee: "INSEE",
    paris: "Paris", dicotopo: "DicoTopo", geonames: "GeoNames", llm: "LLM",
    reference: "référentiel",
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
    correct: "correction des niveaux d'un lieu",
    import: "import du référentiel",
    resolve: "résolution d'un conflit",
    precision: "décision de précision d'arrondissement",
  };
  const JOURNAL_ACTIONS = {
    validate: "Validation",
    reject: "Rejet",
    correct: "Correction des niveaux d'un lieu",
    detach: "Écritures sorties d'un lieu",
    import: "Import du référentiel",
    resolve: "Conflit tranché : décision importée retenue",
    precision: "Précision d'arrondissement",
    undo: "Annulation",
  };
  const PRECISION_STATUS_LABELS = {
    applied: "appliquée", conflict: "conflit", uncertain: "incertaine", ambiguous: "ambiguë",
  };
  const PRECISION_TODO = new Set(["conflict", "uncertain", "ambiguous"]);
  const CLUE_LABELS = {
    code: "code", number: "numéro écrit", street: "rue", manual: "choix manuel",
  };
  const PRECISION_FILTERS = [
    ["todo", "À traiter"],
    ["applied", "Appliquées"],
    ["all", "Toutes"],
  ];
  const JOURNAL_LIMIT = 50;
  const FLASH_MS = 1700;
  const INFO_MS = 6000;

  // -- state -------------------------------------------------------------------

  const state = {
    project: null, // GET /api/project
    clusters: [], // GET /api/clusters, in queue order
    filter: "todo",
    currentId: null,
    detail: null, // GET /api/clusters/{id}
    detailError: null, // message when the open cluster could not be loaded
    unchecked: new Set(), // writings of the open cluster to take out
    chain: [], // level chain being edited, most precise first
    postal: "", // postal code being edited
    notice: null, // {fromId, toId, writings, label} after a split
    flashId: null, // cluster to flash in the queue
    occurrences: null, // null: hidden; else Map writing -> list or Error
    busy: false,
    history: [], // cluster open before each action, to come back on undo
    view: "places", // "places" (validation screen), "registry" or "precisions"
    conflicts: [], // GET /api/registry/conflicts: pending import conflicts
    precisions: [], // GET /api/precisions: every precision group
    precisionFilter: "todo",
    journal: [], // GET /api/registry/journal, newest first
    importSummary: null, // text shown after the last import
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
    if (body instanceof FormData) {
      options.body = body; // multipart: the browser sets the Content-Type
    } else if (body !== undefined) {
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
    const registryButton = $("registry-button");
    const inRegistry = state.view === "registry";
    registryButton.setAttribute("aria-pressed", String(inRegistry));
    const pending = state.conflicts.length;
    registryButton.textContent = inRegistry
      ? "← Retour aux lieux"
      : pending ? `Référentiel (${plural(pending, "conflit", "conflits")})` : "Référentiel";
    registryButton.classList.toggle("alert", pending > 0 && !inRegistry);
    const precisionsButton = $("precisions-button");
    const inPrecisions = state.view === "precisions";
    const toProcess = state.precisions.filter((g) => PRECISION_TODO.has(g.status)).length;
    precisionsButton.setAttribute("aria-pressed", String(inPrecisions));
    precisionsButton.textContent = inPrecisions
      ? "← Retour aux lieux"
      : toProcess ? `Précisions (${toProcess})` : "Précisions";
    precisionsButton.classList.toggle("alert", toProcess > 0 && !inPrecisions);
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
    const inRegistry = state.view === "registry";
    const inPrecisions = state.view === "precisions";
    $("layout").hidden = inRegistry || inPrecisions;
    $("registry").hidden = !inRegistry;
    $("precisions").hidden = !inPrecisions;
    renderHeader();
    renderFilters();
    renderQueue();
    renderDetail();
    if (inRegistry) renderRegistry();
    if (inPrecisions) renderPrecisions();
  }

  // -- detail --------------------------------------------------------------------

  function shownFields(detail) {
    return FIELDS.filter(([kind]) => ALWAYS_SHOWN.has(kind) || kind in detail.view);
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
      renderView(detail),
      renderHistorical(detail),
      renderAlternatives(detail),
      renderChain(detail),
    );
  }

  /** French fixed-field view of the place, read only, with each origin. */
  function renderView(detail) {
    return el(
      "div",
      { class: "fields" },
      shownFields(detail).map(([kind, label]) => {
        const origin = detail.view_origins[kind];
        return el(
          "div",
          null,
          el(
            "label",
            { for: `field-${kind}` },
            label,
            origin ? el("span", { class: "origin", text: `(${ORIGIN_LABELS[origin] || origin})` }) : null,
          ),
          el("input", {
            id: `field-${kind}`,
            type: "text",
            readonly: true,
            tabindex: "-1",
            value: detail.view[kind] ?? "",
          }),
        );
      }),
    );
  }

  function renderHistorical(detail) {
    const writings = Object.entries(detail.historical_writings || {});
    if (!writings.length) return null;
    return el(
      "div",
      { class: "warning" },
      el(
        "span",
        null,
        "Ces écritures désignent une ancienne commune : ",
        writings.map(([writing, name], index) => [
          index ? ", " : "",
          el("code", { text: writing }),
          name ? ` (${name})` : "",
        ]),
        ". Séparez-les pour en faire un lieu distinct.",
      ),
      el("button", {
        type: "button",
        text: "Séparer ces écritures",
        title: "Décocher ces écritures puis les sortir (S)",
        onclick: () => {
          for (const [writing] of writings) state.unchecked.add(writing);
          renderDetail();
        },
      }),
    );
  }

  function chainLabel(levels) {
    return levels.map((level) => level.name).join(", ");
  }

  function renderAlternatives(detail) {
    if (!(detail.alternatives || []).length) return null;
    return el(
      "div",
      null,
      detail.alternatives.map((chain) =>
        el(
          "div",
          { class: "notice" },
          el("span", { text: "Autre lecture possible :" }),
          el("strong", { text: chainLabel(chain) }),
          el("button", {
            type: "button",
            text: "Retenir cette lecture",
            onclick: () => {
              state.chain = chain.map((level) => toDraftLevel(level, false));
              renderDetail();
            },
          }),
        ),
      ),
    );
  }

  // -- level chain editor -----------------------------------------------------

  /**
   * Copy of a level, with what the editor needs to remember. `stored`: the level
   * comes from the place's chain (`detail.levels`), so its rank is the server's.
   */
  function toDraftLevel(level, stored) {
    return {
      ...level,
      serverRank: stored ? level.rank : null,
      originalName: level.name,
      originalType: level.type,
      originalOrigin: level.origin,
    };
  }

  function typeLabel(value) {
    const found = ((state.project && state.project.level_types) || []).find((t) => t.value === value);
    return found ? found.label : value || "";
  }

  /** The type behind what was typed: a known label or slug, else the text itself. */
  function typeValue(text) {
    const typed = text.trim();
    if (!typed) return null;
    const wanted = typed.toLowerCase();
    const found = ((state.project && state.project.level_types) || []).find(
      (t) => t.label.toLowerCase() === wanted || t.value === wanted,
    );
    return found ? found.value : typed;
  }

  function moveLevel(index, step) {
    const target = index + step;
    if (target < 0 || target >= state.chain.length) return;
    const [level] = state.chain.splice(index, 1);
    state.chain.splice(target, 0, level);
    renderDetail();
  }

  function removeLevel(index) {
    state.chain.splice(index, 1);
    renderDetail();
  }

  function addLevel() {
    state.chain.push(
      toDraftLevel({ rank: state.chain.length, name: "", type: null, origin: "manual", status: "validated" }, false),
    );
    renderDetail();
    const names = document.querySelectorAll(".level-name");
    if (names.length) names[names.length - 1].focus();
  }

  function levelButton(text, title, onclick, disabled) {
    return el("button", { type: "button", class: "small", text, title, "aria-label": title, onclick, disabled });
  }

  function renderLevel(level, index) {
    const proposed = level.status === "proposed";
    const pill = el("span", { class: "pill", text: ORIGIN_LABELS[level.origin] || level.origin });
    const last = state.chain.length - 1;
    const row = el(
      "li",
      { class: proposed ? "level proposed" : "level" },
      el("input", {
        type: "text",
        class: "level-name",
        autocomplete: "off",
        spellcheck: "false",
        placeholder: "Nom du niveau",
        "aria-label": `Nom du niveau ${index + 1}`,
        value: level.name,
        oninput: (event) => {
          level.name = event.target.value;
          touched(level, pill);
        },
      }),
      el("input", {
        type: "text",
        class: "level-type",
        autocomplete: "off",
        spellcheck: "false",
        placeholder: "Type",
        list: "level-types",
        "aria-label": `Type du niveau ${index + 1}`,
        value: typeLabel(level.type),
        oninput: (event) => {
          level.type = typeValue(event.target.value);
          touched(level, pill);
        },
      }),
      pill,
      proposed
        ? el(
            "span",
            { class: "level-proposal" },
            level.source ? el("span", { class: "sub", text: `proposé (${level.source})` }) : el("span", { class: "sub", text: "proposé" }),
            el("button", { type: "button", class: "small", text: "Accepter", onclick: () => run(() => acceptLevel(level)) }),
            el("button", { type: "button", class: "small", text: "Refuser", onclick: () => run(() => refuseLevel(level)) }),
          )
        : null,
      el(
        "span",
        { class: "level-buttons" },
        levelButton("↑", "Monter", () => moveLevel(index, -1), index === 0),
        levelButton("↓", "Descendre", () => moveLevel(index, 1), index === last),
        levelButton("✕", "Retirer ce niveau", () => removeLevel(index)),
      ),
    );
    return row;
  }

  /** An edited name or type makes the level manual; refresh its pill. */
  function touched(level, pill) {
    const changed = level.name !== level.originalName || (level.type || null) !== (level.originalType || null);
    level.origin = changed ? "manual" : level.originalOrigin ?? level.origin;
    pill.textContent = ORIGIN_LABELS[level.origin] || level.origin;
  }

  function renderChain(detail) {
    const types = (state.project && state.project.level_types) || [];
    return el(
      "div",
      { class: "chain" },
      el("h3", { text: "Niveaux du lieu, du plus précis au plus large" }),
      el("datalist", { id: "level-types" }, types.map((t) => el("option", { value: t.label }))),
      detail.needs_manual_levels
        ? el("p", { class: "sub", text: "Aucun niveau n'a pu être déduit : saisissez au moins un niveau." })
        : null,
      el("ol", { class: "levels" }, state.chain.map(renderLevel)),
      el(
        "div",
        { class: "chain-footer" },
        el("button", { type: "button", text: "Ajouter un niveau", onclick: addLevel }),
        el(
          "label",
          { class: "postal" },
          "Code postal",
          el("input", {
            type: "text",
            id: "field-postal",
            autocomplete: "off",
            spellcheck: "false",
            value: state.postal,
            oninput: (event) => {
              state.postal = event.target.value;
            },
          }),
        ),
      ),
      el("p", {
        class: "sub",
        text: "Modifiez les niveaux puis validez. Un niveau retiré n'appartient plus au lieu.",
      }),
    );
  }

  /** Levels to send: validated ones and proposals left untouched. */
  function chainBody() {
    return state.chain.map((level, rank) => {
      const { serverRank, originalName, originalType, originalOrigin, ...sent } = level;
      return { ...sent, rank };
    });
  }

  /** Whether the chain or the postal code differ from the stored place. */
  function hasUnsavedEdits() {
    const detail = state.detail;
    const stored = detail.levels.map((level, rank) => ({ ...level, rank }));
    return (
      JSON.stringify(chainBody()) !== JSON.stringify(stored) ||
      state.postal.trim() !== (detail.postal_code || "")
    );
  }

  /** Accept or refuse go to the registry for a stored proposal of a stored place. */
  function storedProposal(level) {
    const detail = state.detail;
    if (!(detail.from_registry && detail.place_id && level.serverRank !== null)) return false;
    if (hasUnsavedEdits()) {
      throw new Error(
        "Des modifications de la chaîne ou du code postal ne sont pas enregistrées : " +
          "cliquez d'abord sur « Enregistrer », ou rouvrez le lieu pour les abandonner.",
      );
    }
    return true;
  }

  async function acceptLevel(level) {
    const detail = state.detail;
    if (storedProposal(level)) {
      await api("POST", `/api/places/${encodeURIComponent(detail.place_id)}/levels/${level.serverRank}/accept`);
      state.history.push(detail.id);
      await refresh();
      await openCluster(clusterById(detail.id) ? detail.id : state.currentId, true);
      showMessage(`Niveau « ${level.name} » accepté.`, "info");
      return;
    }
    // A rule proposal not stored yet: it just joins the chain being edited.
    level.status = "validated";
    renderDetail();
  }

  async function refuseLevel(level) {
    const detail = state.detail;
    if (storedProposal(level)) {
      await api("POST", `/api/places/${encodeURIComponent(detail.place_id)}/levels/${level.serverRank}/refuse`);
      state.history.push(detail.id);
      await refresh();
      await openCluster(clusterById(detail.id) ? detail.id : state.currentId, true);
      showMessage(`Niveau « ${level.name} » refusé.`, "info");
      return;
    }
    state.chain = state.chain.filter((other) => other !== level);
    renderDetail();
  }

  /** Save the chain of a place already in the registry (PUT levels). */
  async function saveLevels() {
    const detail = state.detail;
    if (!detail || !detail.from_registry || !detail.place_id) return;
    await api("PUT", `/api/places/${encodeURIComponent(detail.place_id)}/levels`, {
      levels: chainBody(),
      postal_code: state.postal.trim() || null,
    });
    state.history.push(detail.id);
    await refresh();
    await openCluster(clusterById(detail.id) ? detail.id : state.currentId, true);
    showMessage(`« ${detail.label || "Lieu"} » enregistré.`, "info");
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
      state.detail && state.detail.from_registry
        ? el("button", {
            type: "button",
            text: "Enregistrer",
            title: "Enregistrer les niveaux de ce lieu du référentiel",
            onclick: () => run(saveLevels),
          })
        : null,
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
      const text = state.detailError
        ? `Impossible d'ouvrir ce lieu : ${state.detailError}`
        : state.currentId === null
          ? "Aucun lieu dans ce filtre."
          : "Chargement…";
      section.replaceChildren(el("p", { class: state.detailError ? "empty error" : "empty", text }));
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

  // -- registry screen ---------------------------------------------------------

  /** A place named by its label, else by the start of its id. */
  function placeText(placeId, label) {
    if (label) return `lieu « ${label} »`;
    return placeId ? `lieu ${placeId.slice(0, 8)}…` : "";
  }

  function decisionCell(decision) {
    const rejected = decision.status === "rejected";
    return el(
      "td",
      { title: decision.place_id ? `identifiant du lieu : ${decision.place_id}` : null },
      el("span", {
        class: `state ${decision.status}`,
        text: rejected ? "rejetée (pas un lieu exploitable)" : placeText(decision.place_id, decision.place_label),
      }),
      // Two places may share a label: the id start tells them apart.
      !rejected && decision.place_label && decision.place_id
        ? el("span", { class: "sub place-id", text: `${decision.place_id.slice(0, 8)}…` })
        : null,
    );
  }

  function renderExchange() {
    const input = el("input", {
      id: "import-file",
      type: "file",
      accept: ".json,application/json",
      onchange: () => {
        $("import-button").disabled = !input.files.length;
      },
    });
    return el(
      "div",
      { class: "card" },
      el("h2", null, el("span", { text: "Référentiel personnel" })),
      el("p", {
        class: "sub",
        text: "Vos décisions sur les lieux valent pour tous vos fichiers .gw. Exportez-les pour les partager, "
          + "les sauvegarder ou les versionner (JSON lisible). Importez le fichier d'un autre dossier : "
          + "ce qui est nouveau est ajouté ; une écriture que vous avez déjà décidée autrement devient un "
          + "conflit, à trancher ci-dessous, jamais écrasé en silence.",
      }),
      el(
        "div",
        { class: "actions" },
        el("a", {
          class: "button",
          href: "/api/registry/export",
          download: "referentiel_lieux.json",
          text: "Exporter le référentiel (JSON)",
        }),
      ),
      el(
        "div",
        { class: "actions import" },
        el("label", { for: "import-file", text: "Importer un référentiel :" }),
        input,
        el("button", {
          type: "button",
          id: "import-button",
          class: "primary",
          disabled: true,
          text: "Importer",
          onclick: () => run(importRegistry),
        }),
      ),
      state.importSummary
        ? el("p", { class: "notice", role: "status", text: state.importSummary })
        : null,
    );
  }

  function renderConflicts() {
    const conflicts = state.conflicts;
    const body = conflicts.length
      ? el(
        "table",
        null,
        el(
          "thead",
          null,
          el(
            "tr",
            null,
            el("th", { text: "Écriture" }),
            el("th", { text: "Décision actuelle" }),
            el("th", { text: "Décision importée" }),
            el("th", { text: "Trancher" }),
          ),
        ),
        el(
          "tbody",
          null,
          conflicts.map((c) =>
            el(
              "tr",
              null,
              el("td", null, el("code", { text: c.writing })),
              decisionCell(c.current),
              decisionCell(c.incoming),
              el(
                "td",
                { class: "choices" },
                el("button", {
                  type: "button",
                  text: "Garder l'actuel",
                  "aria-label": `Garder la décision actuelle pour « ${c.writing} »`,
                  onclick: () => run(() => resolveConflict(c.writing, "current")),
                }),
                el("button", {
                  type: "button",
                  class: "primary",
                  text: "Prendre l'importé",
                  "aria-label": `Prendre la décision importée pour « ${c.writing} »`,
                  onclick: () => run(() => resolveConflict(c.writing, "incoming")),
                }),
              ),
            ),
          ),
        ),
      )
      : el("p", { class: "sub", text: "Aucun conflit en attente." });
    return el(
      "div",
      { class: "card" },
      el("h3", { text: `Conflits à trancher (${conflicts.length})` }),
      body,
      el("p", {
        class: "sub",
        text: "Les conflits en attente sont gardés tant que l'atelier tourne ; après un redémarrage, "
          + "réimportez le fichier pour les retrouver.",
      }),
    );
  }

  function formatDate(at) {
    const date = new Date(at);
    return Number.isNaN(date.getTime()) ? at : date.toLocaleString("fr-FR");
  }

  function journalAction(entry) {
    const label = JOURNAL_ACTIONS[entry.action] || entry.action;
    return entry.action === "undo" && entry.undone_entry !== null
      ? `${label} de l'action n° ${entry.undone_entry}`
      : label;
  }

  function journalWritings(entry) {
    const rest = entry.writing_count - entry.writings.length;
    return el(
      "td",
      { class: "writings" },
      entry.writings.map((w) => el("code", { text: w })),
      rest > 0 ? el("span", { class: "sub", text: `et ${rest} autre${rest > 1 ? "s" : ""}` }) : null,
    );
  }

  function renderJournal() {
    const entries = state.journal;
    const body = entries.length
      ? el(
        "table",
        null,
        el(
          "thead",
          null,
          el(
            "tr",
            null,
            el("th", { class: "num", text: "N°" }),
            el("th", { text: "Date" }),
            el("th", { text: "Action" }),
            el("th", { text: "Écriture(s)" }),
            el("th", { text: "Lieu" }),
          ),
        ),
        el(
          "tbody",
          null,
          entries.map((e) =>
            el(
              "tr",
              { class: e.undone ? "undone" : null },
              el("td", { class: "num", text: String(e.entry_id) }),
              el("td", { class: "date", text: formatDate(e.at) }),
              el(
                "td",
                null,
                journalAction(e),
                e.undone ? el("span", { class: "state", text: "annulée" }) : null,
              ),
              journalWritings(e),
              el("td", { title: e.place_id || null, text: e.place_label || (e.place_id ? `${e.place_id.slice(0, 8)}…` : "") }),
            ),
          ),
        ),
      )
      : el("p", { class: "sub", text: "Aucune action enregistrée pour l'instant." });
    return el(
      "div",
      { class: "card" },
      el("h3", { text: `Journal : les ${JOURNAL_LIMIT} dernières actions (lecture seule)` }),
      body,
    );
  }

  function renderRegistry() {
    $("registry").replaceChildren(renderExchange(), renderConflicts(), renderJournal());
  }

  async function loadRegistry() {
    const [conflicts, journal] = await Promise.all([
      api("GET", "/api/registry/conflicts"),
      api("GET", `/api/registry/journal?limit=${JOURNAL_LIMIT}`),
    ]);
    state.conflicts = conflicts.conflicts;
    state.journal = journal.entries;
  }

  // -- precisions (arrondissements) ----------------------------------------------

  const NO_ARRONDISSEMENT = "aucun (n'existait pas à cette date)";
  const NO_ARRONDISSEMENT_MANUAL = "aucun arrondissement (choix manuel)";

  function candidateLabel(candidate) {
    if (!candidate.arrondissement) {
      return candidate.clue === "manual" ? NO_ARRONDISSEMENT_MANUAL : NO_ARRONDISSEMENT;
    }
    return candidate.quartier
      ? `${candidate.arrondissement} · ${candidate.quartier}`
      : candidate.arrondissement;
  }

  function visiblePrecisions() {
    return state.precisions.filter((g) => {
      if (state.precisionFilter === "all") return true;
      return state.precisionFilter === "applied"
        ? g.status === "applied"
        : PRECISION_TODO.has(g.status);
    });
  }

  function renderPrecisionFilters() {
    return el(
      "div",
      { class: "filters", role: "toolbar", "aria-label": "Filtrer les précisions" },
      ...PRECISION_FILTERS.map(([key, label]) => {
        const count = state.precisions.filter((g) => key === "all"
          || (key === "applied" ? g.status === "applied" : PRECISION_TODO.has(g.status))).length;
        return el("button", {
          type: "button",
          "aria-pressed": String(state.precisionFilter === key),
          onclick: () => {
            state.precisionFilter = key;
            renderAll();
          },
          text: `${label} (${count})`,
        });
      }),
    );
  }

  function renderPrecisionGroup(group) {
    const decided = group.status === "applied" && group.candidates.some((c) => c.clue === "manual");
    const choices = group.candidates
      .filter((c) => c.arrondissement_id !== "" && !decided)
      .map((c) => el(
        "li",
        null,
        el("button", {
          type: "button",
          class: "small",
          text: "Retenir",
          title: "Retenir cet arrondissement pour toutes les occurrences du groupe",
          onclick: () => run(() => decidePrecision(group, c.arrondissement_id, c.quartier_id)),
        }),
        " ",
        el("strong", { text: candidateLabel(c) }),
        " ",
        el("span", { class: "pill", text: CLUE_LABELS[c.clue] || c.clue }),
      ));
    const none = group.candidates.find((c) => c.arrondissement_id === "");
    return el(
      "div",
      { class: "card" },
      el(
        "h2",
        null,
        el("code", { text: group.writing }),
        group.complement ? el("code", { text: group.complement }) : null,
        el("span", { class: `state precision-${group.status}`, text: PRECISION_STATUS_LABELS[group.status] || group.status }),
      ),
      el("p", { class: "sub", text: `${group.period_label} · ${plural(group.occurrences, "occurrence", "occurrences")}` }),
      none
        ? el("p", { class: "sub" }, el("span", { class: "pill", text: CLUE_LABELS[none.clue] || none.clue }), ` ${candidateLabel(none)}`)
        : null,
      choices.length ? el("ul", { class: "precision-candidates" }, choices) : null,
      decided
        ? el(
          "ul",
          { class: "precision-candidates" },
          group.candidates
            .filter((c) => c.arrondissement_id !== "")
            .map((c) => el("li", null, "Retenu : ", el("strong", { text: candidateLabel(c) }))),
        )
        : null,
      decided
        ? el(
          "div",
          { class: "actions" },
          el("button", {
            type: "button",
            text: "Revenir au calcul",
            title: "Oublier cette décision : le groupe retrouve son statut calculé",
            onclick: () => run(() => clearPrecision(group)),
          }),
          el("span", { class: "sub", text: " Décision prise : revenez au calcul pour en prendre une autre." }),
        )
        : el(
          "div",
          { class: "actions" },
          el("button", {
            type: "button",
            text: "Aucun arrondissement",
            title: "Aucun arrondissement ne s'applique à ce groupe",
            onclick: () => run(() => decidePrecision(group, "", null)),
          }),
        ),
    );
  }

  function renderPrecisions() {
    const shown = visiblePrecisions();
    $("precisions").replaceChildren(
      el("h2", { text: "Précisions d'arrondissement" }),
      el("p", { class: "sub", text: "Chaque groupe rassemble les occurrences d'une même écriture, d'un même complément et d'une même période. Rien n'est tranché en silence : choisissez l'arrondissement à retenir." }),
      renderPrecisionFilters(),
      ...(shown.length
        ? shown.map(renderPrecisionGroup)
        : [el("p", { class: "empty", text: "Aucune précision dans ce filtre." })]),
    );
  }

  async function loadPrecisions() {
    const result = await api("GET", "/api/precisions");
    state.precisions = result.groups;
  }

  async function decidePrecision(group, arrondissementId, quartierId) {
    await api("POST", "/api/precisions/decide", {
      writing: group.writing,
      complement: group.complement,
      period: group.period,
      arrondissement_id: arrondissementId,
      quartier_id: quartierId,
    });
    state.history.push(state.currentId);
    await loadPrecisions();
    renderAll();
    showMessage(
      arrondissementId === ""
        ? `« ${group.writing} » : aucun arrondissement retenu.`
        : `« ${group.writing} » : arrondissement retenu.`,
      "info",
    );
  }

  async function clearPrecision(group) {
    await api("POST", "/api/precisions/clear", {
      writing: group.writing,
      complement: group.complement,
      period: group.period,
    });
    state.history.push(state.currentId);
    await loadPrecisions();
    renderAll();
    showMessage(`« ${group.writing} » : retour au calcul.`, "info");
  }

  async function showView(view) {
    state.view = view;
    if (view === "precisions") {
      try {
        await loadPrecisions();
      } finally {
        renderAll();
      }
    } else if (view === "registry") {
      try {
        await loadRegistry();
      } finally {
        renderAll();
      }
    } else {
      renderAll();
    }
  }

  /** Reload the queue and the open cluster after the registry changed. */
  async function refreshPlaces() {
    await refresh();
    const id = clusterById(state.currentId) ? state.currentId : firstVisible();
    await openCluster(id);
  }

  async function importRegistry() {
    const input = $("import-file");
    const file = input && input.files.length ? input.files[0] : null;
    if (!file) throw new ApiError("Choisissez d'abord un fichier de référentiel (.json).");
    const form = new FormData();
    form.append("file", file);
    const result = await api("POST", "/api/registry/import", form);
    state.conflicts = result.conflicts;
    await loadRegistry();
    const added = result.added;
    const pending = state.conflicts.length;
    state.importSummary = `Import de « ${file.name} » : `
      + `${plural(added, "décision ajoutée", "décisions ajoutées")}, `
      + `${plural(pending, "conflit", "conflits")} à trancher.`;
    if (added > 0) state.history.push(state.currentId); // the import is undoable
    await refreshPlaces();
    showMessage(state.importSummary, "info");
  }

  async function resolveConflict(writing, keep) {
    try {
      const result = await api("POST", "/api/registry/conflicts/resolve", { writing, keep });
      state.conflicts = result.conflicts;
      if (keep === "incoming") state.history.push(state.currentId);
      showMessage(
        keep === "current"
          ? `« ${writing} » : décision actuelle gardée.`
          : `« ${writing} » : décision importée retenue.`,
        "info",
      );
    } finally {
      // A 409 drops the stale conflict on the server: reload in every case.
      await loadRegistry();
      await refreshPlaces();
    }
  }

  // -- loading -------------------------------------------------------------------

  async function refresh() {
    const [project, clusters, conflicts, precisions] = await Promise.all([
      api("GET", "/api/project"),
      api("GET", "/api/clusters"),
      api("GET", "/api/registry/conflicts"),
      api("GET", "/api/precisions"),
    ]);
    state.precisions = precisions.groups;
    state.project = project;
    state.clusters = clusters;
    state.conflicts = conflicts.conflicts;
  }

  /** Open a cluster; `keepNotice` keeps the banner of a split just made. */
  async function openCluster(id, keepNotice) {
    if (!keepNotice) state.notice = null;
    state.unchecked = new Set();
    state.occurrences = null;
    state.currentId = id;
    state.detail = null;
    state.detailError = null;
    try {
      if (id !== null) {
        state.detail = await api("GET", clusterPath(id));
        state.chain = state.detail.levels.map((level) => toDraftLevel(level, true));
        state.postal = state.detail.postal_code || "";
      }
    } catch (error) {
      // Shown in the detail pane; run() also shows it in the message.
      state.detailError = error.message;
      throw error;
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
    // While an action runs, run() would drop the opening of the first item:
    // keep the filter as it is, so the list and the open cluster stay in sync.
    if (state.busy) return;
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
    const writings = detail.writings.map((w) => w.text);
    const checked = writings.filter((w) => !state.unchecked.has(w));
    const taken = writings.filter((w) => state.unchecked.has(w));
    const next = nextAfterCurrent();
    const result = await api("POST", clusterPath(detail.id, "validate"), {
      levels: chainBody(),
      postal_code: state.postal.trim() || null,
      checked,
    });
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
    if (state.view === "registry") {
      await loadRegistry();
      renderAll();
    }
    renderAll(); // the precision list and its counter follow the undo
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
    if (state.view !== "places") {
      // The place shortcuts act on the hidden cluster: off on these screens.
      if (key === "Escape") run(() => showView("places"));
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
    $("registry-button").addEventListener("click", () => {
      run(() => showView(state.view === "registry" ? "places" : "registry"));
    });
    $("precisions-button").addEventListener("click", () => {
      run(() => showView(state.view === "precisions" ? "places" : "precisions"));
    });
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
