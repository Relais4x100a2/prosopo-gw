'use strict';

// ==================== STATE ====================
const state = {
  token: sessionStorage.getItem('gwToken') || null,
  expiresAt: sessionStorage.getItem('gwExpiresAt') || null,
  stats: null,
  persons: { items: [], page: 1, pages: 1, query: '', filters: {}, loaded: false },
  families: { items: [], page: 1, pages: 1, nameMap: {}, loaded: false },
  // Dernière adresse vue par onglet : revenir sur un onglet retrouve son contexte.
  lastRoute: {},
  // id → « NOM, Prénoms » : évite de redemander un nom déjà connu.
  nameCache: new Map(),
};

// ==================== UTILITAIRES ====================
function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function shortDate(dateStr) {
  if (!dateStr) return '';
  const m = String(dateStr).match(/(\d{4})/);
  return m ? m[1] : String(dateStr);
}

// ==================== API HELPERS ====================
async function apiFetch(path, options = {}) {
  const headers = { 'X-Session-Token': state.token, ...options.headers };
  const res = await fetch(path, { ...options, headers });
  if (res.status === 401) {
    handleExpiry();
    throw new Error('session-expired');
  }
  return res;
}

async function apiJson(path, options = {}) {
  const res = await apiFetch(path, options);
  if (!res.ok) throw Object.assign(new Error('api-error'), { status: res.status });
  return res.json();
}

// ==================== AFFICHAGE DES NOMS ====================
// Le format .gw remplace les espaces par « _ » (« Jean_Pierre », « DUPONT_MARTIN »).
// Ces helpers ne servent qu'à l'affichage : les identifiants restent bruts.
function formatGwName(raw) {
  return String(raw || '').replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
}

// « NOM, Prénoms » lisible ; « — » pour une partie manquante.
function personLabel(surname, firstName) {
  return `${formatGwName(surname) || '—'}, ${formatGwName(firstName) || '—'}`;
}

// ==================== SESSION ====================
async function uploadFile(file) {
  const form = new FormData();
  form.append('file', file);
  let res;
  try {
    res = await fetch('/api/v1/sessions/', { method: 'POST', body: form });
  } catch {
    showUploadError('Impossible de joindre le serveur.');
    return;
  }
  if (res.status === 413) { showUploadError('Fichier trop volumineux pour ce serveur.'); return; }
  if (res.status === 400 || res.status === 415) { showUploadError('Format invalide, attendu .gw ou .gwplus'); return; }
  if (res.status === 503) { showUploadError('Serveur saturé, réessayez dans quelques minutes.'); return; }
  if (res.status === 429) { showUploadError('Trop de tentatives, réessayez plus tard.'); return; }
  if (!res.ok) { showUploadError('Erreur inattendue, réessayez.'); return; }

  const data = await res.json();
  state.token = data.session_token;
  state.expiresAt = data.expires_at;
  sessionStorage.setItem('gwToken', state.token);
  sessionStorage.setItem('gwExpiresAt', state.expiresAt);
  await enterApp();
}

async function deleteSession() {
  if (!state.token) return;
  try {
    await fetch(`/api/v1/sessions/${state.token}`, {
      method: 'DELETE',
      headers: { 'X-Session-Token': state.token },
    });
  } catch { /* ignore network errors on delete */ }
  clearSession();
}

function clearSession() {
  state.token = null;
  state.nameCache.clear();
  resetLoadedData();
  state.expiresAt = null;
  sessionStorage.removeItem('gwToken');
  sessionStorage.removeItem('gwExpiresAt');
  if (_timerInterval) { clearInterval(_timerInterval); _timerInterval = null; }
  showLanding();
}

// Une nouvelle session ne doit rien afficher de la précédente.
function resetLoadedData() {
  state.persons = { items: [], page: 1, pages: 1, query: '', filters: {}, loaded: false };
  state.evtRouteKey = '';
  state.families = { items: [], page: 1, pages: 1, nameMap: {}, loaded: false };
  state.lastRoute = {};
  closeDetail();
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
}

function handleExpiry() {
  clearSession();
  showLanding();
  showUploadError('Votre session a expiré. Rechargez votre fichier pour continuer.');
}

// ==================== VIEWS ====================
function showLanding() {
  document.getElementById('view-landing').style.display = '';
  document.getElementById('view-app').style.display = 'none';
}

function showApp() {
  document.getElementById('view-landing').style.display = 'none';
  document.getElementById('view-app').style.display = '';
}

function showUploadError(msg) {
  const el = document.getElementById('upload-error');
  el.textContent = msg;
  el.style.display = '';
}

function hideUploadError() {
  document.getElementById('upload-error').style.display = 'none';
}

// ==================== INIT ====================
async function enterApp() {
  showApp();
  await loadStats();
  startTimer();
  if (!parseRoute().known) history.replaceState(null, '', '#/personnes');
  await applyRoute();
}

async function init() {
  wireUploadZone();
  wireQuit();
  wireTabs();
  wirePersonsTab();
  wireFamiliesTab();
  initEventsTab();
  wireExportTab();
  wireDrawer();
  window.addEventListener('hashchange', applyRoute);

  if (state.token) {
    try {
      await enterApp();
    } catch {
      clearSession();
      showLanding();
    }
  } else {
    showLanding();
  }
}

window.addEventListener('DOMContentLoaded', init);

// ==================== UPLOAD ZONE ====================
const GW_EXTENSIONS = ['.gw', '.gwplus'];

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} Ko`;
  return `${(bytes / 1024 / 1024).toFixed(1)} Mo`;
}

function setUploadBusy(busy, file) {
  const zone = document.getElementById('drop-zone');
  const title = document.getElementById('drop-title');
  const hint = document.getElementById('drop-hint');
  const btn = document.getElementById('btn-upload');
  zone.classList.toggle('busy', busy);
  zone.setAttribute('aria-busy', String(busy));
  btn.disabled = busy;
  if (file) title.textContent = `${file.name} · ${formatSize(file.size)}`;
  hint.textContent = busy
    ? 'Envoi et analyse en cours…'
    : 'Glissez un autre fichier ou cliquez pour changer';
}

// Un fichier choisi (dépôt ou sélecteur) est chargé immédiatement.
async function startUpload(file) {
  hideUploadError();
  if (!file) { showUploadError('Sélectionnez un fichier .gw.'); return; }
  const name = file.name.toLowerCase();
  if (!GW_EXTENSIONS.some(ext => name.endsWith(ext))) {
    showUploadError(`« ${file.name} » n'est pas un fichier .gw ou .gwplus.`);
    return;
  }
  setUploadBusy(true, file);
  try {
    await uploadFile(file);
  } finally {
    setUploadBusy(false);
  }
}

function wireUploadZone() {
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');
  const uploadBtn = document.getElementById('btn-upload');
  const isBusy = () => dropZone.classList.contains('busy');

  const openPicker = () => { if (!isBusy()) fileInput.click(); };
  dropZone.addEventListener('click', openPicker);
  dropZone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openPicker(); }
  });
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    if (!isBusy()) dropZone.classList.add('dragover');
  });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (isBusy()) return;
    startUpload(e.dataTransfer.files[0]);
  });

  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    fileInput.value = '';   // permet de re-sélectionner le même fichier
    if (file) startUpload(file);
  });

  // Repli : relance le dernier choix ou ouvre le sélecteur.
  uploadBtn.addEventListener('click', openPicker);
}

function wireQuit() {
  document.getElementById('btn-quit').addEventListener('click', async () => {
    await deleteSession();
  });
}

// ==================== NAVBAR ====================
async function loadStats() {
  const data = await apiJson('/api/v1/genealogy/stats');
  state.stats = data.data;
  document.getElementById('nav-stats').textContent =
    `${state.stats.total_persons} personnes · ${state.stats.total_families} familles`;
}

let _timerInterval = null;

function startTimer() {
  if (_timerInterval) clearInterval(_timerInterval);
  updateTimer();
  _timerInterval = setInterval(updateTimer, 30000);
}

function updateTimer() {
  if (!state.expiresAt) return;
  const remaining = Math.max(0, new Date(state.expiresAt) - Date.now());
  const h = Math.floor(remaining / 3600000);
  const m = Math.floor((remaining % 3600000) / 60000);
  document.getElementById('nav-timer').textContent =
    remaining > 0 ? `⏱ ${h > 0 ? h + 'h ' : ''}${m} min` : '⌛ Expiré';
}

// ==================== TABS ====================
function wireTabs() {
  document.querySelectorAll('.pgw-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      const name = tab.dataset.tab;
      navigate(state.lastRoute[name] || '#/' + TAB_ROUTES[name]);
    });
  });
}

function showTab(name) {
  document.querySelectorAll('.pgw-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `panel-${name}`));
  if (name === 'stats') renderStats();
}

// ==================== ROUTAGE (hash) ====================
// L'adresse décrit la vue : retour/avant du navigateur, rechargement et liens partagés.
//   #/personnes?q=…&page=N   #/personne/<id>
//   #/familles?page=N        #/famille/<id>
//   #/evenements   #/stats   #/export
// Les clics ne font que changer l'adresse ; applyRoute() est le seul à afficher.
const ROUTE_TABS = {
  personnes: 'persons', personne: 'persons',
  familles: 'families', famille: 'families',
  evenements: 'events', stats: 'stats', export: 'export',
};
const TAB_ROUTES = {
  persons: 'personnes', families: 'familles', events: 'evenements', stats: 'stats', export: 'export',
};

function parseRoute(hash = location.hash) {
  const raw = hash.replace(/^#\/?/, '');
  const qIdx = raw.indexOf('?');
  const path = qIdx === -1 ? raw : raw.slice(0, qIdx);
  const params = new URLSearchParams(qIdx === -1 ? '' : raw.slice(qIdx + 1));
  const slash = path.indexOf('/');
  const name = slash === -1 ? path : path.slice(0, slash);
  let id = null;
  if (slash !== -1) {
    try { id = decodeURIComponent(path.slice(slash + 1)) || null; } catch { id = null; }
  }
  const known = name in ROUTE_TABS && (id !== null) === (name === 'personne' || name === 'famille');
  return known
    ? { known, name, tab: ROUTE_TABS[name], id, params }
    : { known, name: 'personnes', tab: 'persons', id: null, params: new URLSearchParams() };
}

function pageParam(params) {
  return Math.max(1, parseInt(params.get('page'), 10) || 1);
}

// Filtres de liste posés depuis les Stats : nom de famille, décennie de naissance, lieu.
//   #/personnes?nom=DUPONT   ?ne=1850-1859   ?lieu=Paris
const PERSON_FILTERS = {
  nom: 'Nom',
  ne: 'Naissance',
  lieu: 'Lieu',
};

function personFiltersFrom(params) {
  const f = {};
  for (const key of Object.keys(PERSON_FILTERS)) {
    const v = (params.get(key) || '').trim();
    if (v) f[key] = v;
  }
  return f;
}

const sameFilters = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// « 1850-1859 » → [1850, 1859] ; « 1850 » → [1850, 1850] ; sinon null.
function yearRange(text) {
  const m = /^(\d{3,4})(?:-(\d{3,4}))?$/.exec(text || '');
  return m ? [Number(m[1]), Number(m[2] || m[1])] : null;
}

function personsListHash(page = state.persons.page, query = state.persons.query,
                         filters = state.persons.filters) {
  const p = new URLSearchParams();
  if (query) p.set('q', query);
  for (const [k, v] of Object.entries(filters || {})) p.set(k, v);
  if (page > 1) p.set('page', page);
  const qs = p.toString();
  return '#/personnes' + (qs ? '?' + qs : '');
}
function familiesListHash(page = state.families.page) {
  return '#/familles' + (page > 1 ? '?page=' + page : '');
}
const personHash = id => '#/personne/' + encodeURIComponent(id);
const familyHash = id => '#/famille/' + encodeURIComponent(id);

function navigate(hash) {
  if (location.hash === hash) applyRoute();   // même adresse : pas de hashchange
  else location.hash = hash;
}

let _routeSeq = 0;

async function applyRoute() {
  if (!state.token) return;
  const seq = ++_routeSeq;
  const route = parseRoute();
  // Adresse inconnue ou mal formée : on la remplace par la liste des personnes.
  if (!route.known) history.replaceState(null, '', personsListHash());
  state.lastRoute[route.tab] = location.hash;
  showTab(route.tab);
  try {
    if (route.name === 'personnes') {
      const query = route.params.get('q') || '';
      const filters = personFiltersFrom(route.params);
      const page = pageParam(route.params);
      closeDetail();
      document.getElementById('persons-search').value = query;
      if (!state.persons.loaded || state.persons.query !== query || state.persons.page !== page
          || !sameFilters(state.persons.filters, filters)) {
        await loadPersons(page, query, filters);
      }
    } else if (route.name === 'personne') {
      if (!state.persons.loaded) await loadPersons(1, '', {});
      if (seq === _routeSeq) await openPersonDetail(route.id);
    } else if (route.name === 'familles') {
      const page = pageParam(route.params);
      closeDetail();
      if (!state.families.loaded || state.families.page !== page) await loadFamilies(page);
    } else if (route.name === 'famille') {
      if (!state.families.loaded) await loadFamilies(1);
      if (seq === _routeSeq) await openFamilyDetail(route.id);
    } else {
      closeDetail();   // Événements, Stats, Export : pas de fiche
      if (route.name === 'evenements') applyEventsRoute(route.params);
    }
  } catch { /* session expirée : gérée par apiFetch ; autres erreurs déjà affichées */ }
}

// ==================== PERSONNES ====================
let _personsSeq = 0;
let _familiesSeq = 0;

function wirePersonsTab() {
  const searchInput = document.getElementById('persons-search');
  const searchBtn = document.getElementById('persons-search-btn');
  const clearBtn = document.getElementById('persons-clear-btn');
  const prevBtn = document.getElementById('persons-prev');
  const nextBtn = document.getElementById('persons-next');

  const search = () => navigate(personsListHash(1, searchInput.value.trim()));
  searchBtn.addEventListener('click', search);
  searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });

  // ✕ vide la recherche et les filtres.
  clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    navigate(personsListHash(1, '', {}));
  });

  prevBtn.addEventListener('click', () => navigate(personsListHash(state.persons.page - 1)));
  nextBtn.addEventListener('click', () => navigate(personsListHash(state.persons.page + 1)));
}

async function loadPersons(page, query, filters = {}) {
  const seq = ++_personsSeq;
  const params = new URLSearchParams({ page, size: 50 });
  if (query) params.set('query', query);
  if (filters.nom) params.set('surname', filters.nom);
  if (filters.lieu) params.set('place', filters.lieu);
  const years = yearRange(filters.ne);
  if (years) {
    params.set('birth_year_from', years[0]);
    params.set('birth_year_to', years[1]);
  }
  const url = '/api/v1/persons/?' + params;
  let data;
  try {
    data = await apiJson(url);
  } catch (err) {
    if (seq === _personsSeq) {
      document.getElementById('persons-list').innerHTML =
        '<p class="alert-pgw error">Impossible de charger les personnes.</p>';
    }
    throw err;
  }
  if (seq !== _personsSeq) return;
  rememberNames(data.items);
  state.persons.loaded = true;
  state.persons.query = query || '';
  state.persons.filters = filters;
  state.persons.items = data.items;
  state.persons.page = data.pagination.page;
  state.persons.pages = data.pagination.pages;
  renderPersons();
  renderPersonFilters();
  updatePersonPagination(data.pagination);
}

// Pastilles des filtres actifs ; ✕ retire un filtre (l'adresse suit).
function renderPersonFilters() {
  const bar = document.getElementById('persons-filters');
  const filters = state.persons.filters;
  const keys = Object.keys(filters);
  bar.hidden = !keys.length;
  bar.innerHTML = keys.map(k => {
    const rest = { ...filters };
    delete rest[k];
    const value = k === 'ne' ? filters[k].replace('-', '–') : formatGwName(filters[k]);
    return `<span class="filter-chip">${escHtml(PERSON_FILTERS[k])} : <strong>${escHtml(value)}</strong>`
      + ` <a href="${escHtml(personsListHash(1, state.persons.query, rest))}" aria-label="Retirer le filtre ${escHtml(PERSON_FILTERS[k])}">✕</a></span>`;
  }).join('');
}

function renderPersons() {
  const list = document.getElementById('persons-list');
  if (!state.persons.items.length) {
    list.innerHTML = '<p class="text-muted list-empty">Aucune personne trouvée.</p>';
    return;
  }
  list.innerHTML = state.persons.items.map(p => {
    const metaParts = [];
    if (p.birth_date) metaParts.push(`°${shortDate(p.birth_date)}`);
    if (p.death_date) metaParts.push(`†${shortDate(p.death_date)}`);
    const meta = metaParts.join(' · ');
    return `<div class="item-row">
      <span><span class="item-name"><strong>${escHtml(formatGwName(p.surname) || '—')}</strong>, ${escHtml(formatGwName(p.first_name) || '—')}</span> <span class="item-meta">${escHtml(meta)}</span></span>
      <button class="btn-see" data-id="${escHtml(p.id)}">Voir ›</button>
    </div>`;
  }).join('');
  list.querySelectorAll('.btn-see').forEach(btn => {
    // « Voir » ouvre la fiche ; re-cliquer sur la fiche ouverte la referme.
    btn.addEventListener('click', () => navigate(
      drawerShows('person', btn.dataset.id)
        ? personsListHash()
        : personHash(btn.dataset.id)));
  });
  markActiveRows();
}

function updatePersonPagination(pagination) {
  document.getElementById('persons-prev').disabled = !pagination.has_prev;
  document.getElementById('persons-next').disabled = !pagination.has_next;
  document.getElementById('persons-page-info').textContent =
    `Page ${pagination.page} / ${pagination.pages} (${pagination.total} personnes)`;
  // Pas de pagination « Page 1 / 0 » quand il n'y a aucun résultat.
  document.querySelector('#panel-persons .pagination-bar').hidden = !pagination.total;
}

// ==================== PANNEAU LATÉRAL ====================
// Une seule fiche à la fois (personne ou famille), à droite de la liste qui reste
// stable ; plein écran sur mobile. Le fil d'Ariane garde les fiches consultées.
const TRAIL_MAX = 8;
let _detailSeq = 0;      // annule les ouvertures dépassées par une plus récente
let _trail = [];         // [{ hash, label, title }]

function drawerShows(kind, id) {
  const drawer = document.getElementById('detail-drawer');
  return !drawer.hidden && drawer.dataset.kind === kind && drawer.dataset.id === id;
}

function setDrawerOpen(open) {
  document.getElementById('detail-drawer').hidden = !open;
  document.body.classList.toggle('drawer-open', open);
}

// Pendant le chargement : panneau ouvert, contenu précédent grisé.
function setDrawerLoading(loading) {
  const drawer = document.getElementById('detail-drawer');
  drawer.setAttribute('aria-busy', String(loading));
  if (loading && drawer.hidden) {
    document.getElementById('drawer-body').innerHTML =
      '<p class="text-muted drawer-loading">Chargement…</p>';
    renderTrail();
    setDrawerOpen(true);
  }
}

function showInDrawer(content, kind, id, crumb) {
  const drawer = document.getElementById('detail-drawer');
  const body = document.getElementById('drawer-body');
  drawer.dataset.kind = kind;
  drawer.dataset.id = id;
  body.replaceChildren(content);
  body.scrollTop = 0;
  if (crumb) pushTrail(crumb);
  renderTrail();
  setDrawerLoading(false);
  setDrawerOpen(true);
  markActiveRows();
  // Lecteurs d'écran / clavier : le focus suit la fiche affichée.
  body.querySelector('.drawer-title')?.focus({ preventScroll: true });
}

function closeDetail() {
  _detailSeq++;
  const drawer = document.getElementById('detail-drawer');
  if (!drawer) return;
  delete drawer.dataset.kind;
  delete drawer.dataset.id;
  document.getElementById('drawer-body').replaceChildren();
  _trail = [];
  setDrawerLoading(false);
  setDrawerOpen(false);
  markActiveRows();
}

// Revenir à une fiche déjà dans le fil le tronque après elle (comme un historique).
function pushTrail(crumb) {
  const idx = _trail.findIndex(c => c.hash === crumb.hash);
  if (idx !== -1) _trail = _trail.slice(0, idx);
  _trail.push(crumb);
  if (_trail.length > TRAIL_MAX) _trail = _trail.slice(-TRAIL_MAX);
}

function renderTrail() {
  const nav = document.getElementById('drawer-trail');
  nav.innerHTML = _trail.map((c, i) => i === _trail.length - 1
    ? `<span class="crumb current" aria-current="page" title="${escHtml(c.title)}">${escHtml(c.label)}</span>`
    : `<a class="crumb" href="${escHtml(c.hash)}" title="${escHtml(c.title)}">${escHtml(c.label)}</a>`
  ).join('<span class="crumb-sep" aria-hidden="true">›</span>');
}

// La ligne de la fiche ouverte reste repérable dans la liste.
function markActiveRows() {
  const drawer = document.getElementById('detail-drawer');
  const open = drawer && !drawer.hidden ? drawer.dataset : {};
  for (const [listId, kind] of [['persons-list', 'person'], ['families-list', 'family']]) {
    document.querySelectorAll(`#${listId} .item-row`).forEach(row => {
      const btn = row.querySelector('.btn-see');
      const active = !!btn && open.kind === kind && open.id === btn.dataset.id;
      row.classList.toggle('is-active', active);
      if (btn) btn.setAttribute('aria-expanded', String(active));
    });
  }
}

// Fermer revient à la liste de l'onglet courant (l'adresse suit).
function closeDrawerRoute() {
  navigate(parseRoute().tab === 'families' ? familiesListHash() : personsListHash());
}

function wireDrawer() {
  document.getElementById('drawer-close').addEventListener('click', closeDrawerRoute);
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || document.getElementById('detail-drawer').hidden) return;
    if (e.target.closest && e.target.closest('input, select, textarea')) return;
    closeDrawerRoute();
  });
}

function drawerError(message) {
  const p = document.createElement('p');
  p.className = 'alert-pgw error';
  p.textContent = message;
  return p;
}

// ==================== FICHE PERSONNE ====================
async function openPersonDetail(personId) {
  if (drawerShows('person', personId)) return;
  const seq = ++_detailSeq;
  setDrawerLoading(true);

  let personResp, familiesResp;
  try {
    [personResp, familiesResp] = await Promise.all([
      apiJson('/api/v1/persons/' + encodeURIComponent(personId)),
      apiJson('/api/v1/persons/' + encodeURIComponent(personId) + '/families'),
    ]);
  } catch (err) {
    if (err.message === 'session-expired' || seq !== _detailSeq) return;
    showInDrawer(drawerError('Impossible de charger la fiche.'), 'person', personId, null);
    return;
  }
  if (seq !== _detailSeq) return;

  const person = personResp.data;
  const families = familiesResp.data || [];

  const spouseFamilyIds = new Set(person.related_families || []);

  const parentIds = [];
  const childIds = [];
  const partnerIds = [];
  const unions = [];   // familles où la personne est conjoint : lien vers la fiche famille

  // myId = authoritative ID from server (avoids any HTML-attribute encoding drift)
  const myId = person.id || personId;

  for (const fam of families) {
    const isSpouseFamily = spouseFamilyIds.size > 0
      ? spouseFamilyIds.has(fam.id)
      : (fam.husband_id === myId || fam.wife_id === myId);
    if (isSpouseFamily) {
      // person is a parent/spouse in this family → collect children + partner
      for (const child of (fam.children || [])) {
        const cid = child.person_id || child; // ChildSchema object or plain id
        if (cid && cid !== myId) childIds.push(cid);
      }
      // collect both spouse IDs, then exclude ourselves
      for (const sid of [fam.husband_id, fam.wife_id]) {
        if (sid && sid !== myId) partnerIds.push(sid);
      }
      const partnerId = [fam.husband_id, fam.wife_id].find(sid => sid && sid !== myId) || null;
      unions.push({ familyId: fam.id, partnerId, date: fam.marriage_date, place: fam.marriage_place });
    } else {
      // person is a child in this family → collect parents
      if (fam.husband_id) parentIds.push(fam.husband_id);
      if (fam.wife_id) parentIds.push(fam.wife_id);
    }
  }

  const uniqueParentIds = [...new Set(parentIds)];
  const uniqueChildIds = [...new Set(childIds)];
  const uniquePartnerIds = [...new Set(partnerIds)];
  const allIds = [...new Set([...uniqueParentIds, ...uniqueChildIds, ...uniquePartnerIds])];

  const nameMap = await resolvePersonNames(allIds);
  if (seq !== _detailSeq) return;   // une autre fiche a été demandée entre-temps

  const parents = uniqueParentIds.map(id => ({ id, label: nameMap[id] || id }));
  const children = uniqueChildIds.map(id => ({ id, label: nameMap[id] || id }));
  const partners = uniquePartnerIds.map(id => ({ id, label: nameMap[id] || id }));

  const panel = buildPersonDetailPanel(person, parents, partners, children);
  panel.dataset.personId = personId;
  if (unions.length) panel.append(buildUnionsSection(unions, nameMap));

  showInDrawer(panel, 'person', personId, {
    hash: personHash(personId),
    label: formatGwName(person.first_name) || formatGwName(person.surname) || personId,
    title: personLabel(person.surname, person.first_name),
  });
}

function buildUnionsSection(unions, nameMap) {
  const section = document.createElement('div');
  section.className = 'drawer-section';
  section.innerHTML = `<div class="mini-tree-label">Familles</div>` + unions.map(u => {
    const who = u.partnerId ? `avec ${nameMap[u.partnerId] || u.partnerId}` : 'conjoint inconnu';
    const when = [u.date ? '⚭ ' + shortDate(u.date) : '', formatGwName(u.place)].filter(Boolean).join(' · ');
    return `<a class="mini-tree-person" href="${escHtml(familyHash(u.familyId))}">${escHtml(who)}`
      + (when ? ` <span class="item-meta">${escHtml(when)}</span>` : '') + '</a>';
  }).join('');
  return section;
}

// Au plus MAX_NAME_IDS identifiants par appel (plafond de GET /persons/names).
const MAX_NAME_IDS = 200;

function rememberNames(persons) {
  for (const p of persons || []) {
    if (p && p.id) state.nameCache.set(p.id, personLabel(p.surname, p.first_name));
  }
}

// Résout les noms en lot : une requête pour toute une page au lieu d'une par personne
// (le N+1 épuisait vite la limite de 600 requêtes/minute).
async function resolvePersonNames(ids) {
  const wanted = [...new Set(ids.filter(Boolean))];
  const missing = wanted.filter(id => !state.nameCache.has(id));
  for (let i = 0; i < missing.length; i += MAX_NAME_IDS) {
    const chunk = missing.slice(i, i + MAX_NAME_IDS);
    const params = new URLSearchParams();
    chunk.forEach(id => params.append('ids', id));
    let found = {};
    try {
      found = (await apiJson('/api/v1/persons/names?' + params)).data || {};
    } catch (err) {
      if (err.message === 'session-expired') throw err;
      continue;   // échec réseau : on affichera les identifiants bruts, sans les mémoriser
    }
    for (const id of chunk) {
      const p = found[id];
      state.nameCache.set(id, p ? personLabel(p.surname, p.first_name) : id);
    }
  }
  const map = {};
  for (const id of wanted) map[id] = state.nameCache.get(id) || id;
  return map;
}

function buildPersonDetailPanel(person, parents, partners, children) {
  const panel = document.createElement('div');
  panel.id = 'person-detail-panel';
  panel.className = 'person-detail';
  const fullName = escHtml(personLabel(person.surname, person.first_name));

  const dateParts = [];
  if (person.birth_date) dateParts.push('°' + escHtml(shortDate(person.birth_date)));
  if (person.death_date) dateParts.push('†' + escHtml(shortDate(person.death_date)));
  const datesHtml = dateParts.length
    ? `<span style="color:var(--text-muted);font-size:0.85rem"> — ${dateParts.join(' · ')}</span>`
    : '';

  function renderPersonNodes(list) {
    if (!list.length) return '<span class="mini-tree-person placeholder">—</span>';
    return list.map(({ id, label }) =>
      `<a class="mini-tree-person" href="${escHtml(personHash(id))}" data-id="${escHtml(id)}">${escHtml(label)}</a>`
    ).join('');
  }

  const partnersHtml = partners.length
    ? `<div class="mini-tree-label" style="margin-top:0.4rem">⚭ Partenaire(s)</div>${renderPersonNodes(partners)}`
    : '';

  panel.innerHTML = `
    <h2 class="drawer-title" tabindex="-1">${fullName}${datesHtml}</h2>
    <div class="mini-tree">
      <div class="mini-tree-col">
        <div class="mini-tree-label">Parents</div>
        ${renderPersonNodes(parents)}
      </div>
      <div class="mini-tree-arrow">→</div>
      <div class="mini-tree-col">
        <div class="mini-tree-label">Lui/Elle</div>
        <span class="mini-tree-person self">${fullName}</span>
        ${partnersHtml}
      </div>
      <div class="mini-tree-arrow">→</div>
      <div class="mini-tree-col">
        <div class="mini-tree-label">Enfants</div>
        ${renderPersonNodes(children)}
      </div>
    </div>
  `;

  return panel;
}

// ==================== FAMILLES ====================
function wireFamiliesTab() {
  document.getElementById('families-prev').addEventListener('click', () => {
    navigate(familiesListHash(state.families.page - 1));
  });
  document.getElementById('families-next').addEventListener('click', () => {
    navigate(familiesListHash(state.families.page + 1));
  });
}

async function loadFamilies(page) {
  const seq = ++_familiesSeq;
  const url = `/api/v1/families/?page=${page}&size=50`;
  let data;
  try {
    data = await apiJson(url);
  } catch (err) {
    if (seq === _familiesSeq) {
      document.getElementById('families-list').innerHTML =
        '<p class="alert-pgw error">Impossible de charger les familles.</p>';
    }
    throw err;
  }
  if (seq !== _familiesSeq) return;

  // Resolve spouse names
  const spouseIds = [...new Set(
    data.items.flatMap(f => [f.husband_id, f.wife_id].filter(Boolean))
  )];
  const nameMap = await resolvePersonNames(spouseIds);
  if (seq !== _familiesSeq) return; // check again after async name resolution

  state.families.loaded = true;
  state.families.items = data.items;
  state.families.nameMap = nameMap; // store for renderFamilies
  state.families.page = data.pagination.page;
  state.families.pages = data.pagination.pages;
  renderFamilies();
  updateFamiliesPagination(data.pagination);
}

function renderFamilies() {
  const list = document.getElementById('families-list');
  if (!state.families.items.length) {
    list.innerHTML = '<p class="text-muted list-empty">Aucune famille trouvée.</p>';
    return;
  }
  list.innerHTML = state.families.items.map(f => {
    const husband = f.husband_id
      ? escHtml(state.families.nameMap[f.husband_id] || f.husband_id)
      : '—';
    const wife = f.wife_id
      ? escHtml(state.families.nameMap[f.wife_id] || f.wife_id)
      : '—';
    const childCount = Number.isInteger(f.children_count)
      ? f.children_count
      : (Array.isArray(f.children) ? f.children.length : 0);
    const metaParts = [`${childCount} enfant(s)`];
    if (f.marriage_date) metaParts.push(`⚭ ${escHtml(shortDate(f.marriage_date))}`);
    const meta = metaParts.join(' · ');
    return `<div class="item-row">
      <span><span class="item-name"><strong>${husband}</strong> &amp; <strong>${wife}</strong></span> <span class="item-meta">${meta}</span></span>
      <button class="btn-see" data-id="${escHtml(f.id)}">Voir ›</button>
    </div>`;
  }).join('');
  list.querySelectorAll('.btn-see').forEach(btn => {
    btn.addEventListener('click', () => navigate(
      drawerShows('family', btn.dataset.id)
        ? familiesListHash()
        : familyHash(btn.dataset.id)));
  });
  markActiveRows();
}

function updateFamiliesPagination(pagination) {
  document.getElementById('families-prev').disabled = !pagination.has_prev;
  document.getElementById('families-next').disabled = !pagination.has_next;
  document.getElementById('families-page-info').textContent =
    `Page ${pagination.page} / ${pagination.pages} (${pagination.total} familles)`;
  document.querySelector('#panel-families .pagination-bar').hidden = !pagination.total;
}

async function openFamilyDetail(familyId) {
  if (drawerShows('family', familyId)) return;
  const seq = ++_detailSeq;
  setDrawerLoading(true);

  let familyResp, childrenResp;
  try {
    [familyResp, childrenResp] = await Promise.all([
      apiJson('/api/v1/families/' + encodeURIComponent(familyId)),
      apiJson('/api/v1/families/' + encodeURIComponent(familyId) + '/children'),
    ]);
  } catch (err) {
    if (err.message === 'session-expired' || seq !== _detailSeq) return;
    showInDrawer(drawerError('Impossible de charger la famille.'), 'family', familyId, null);
    return;
  }
  if (seq !== _detailSeq) return;

  const family = familyResp.data || {};
  const children = childrenResp.data || [];
  const spouseIds = [family.husband_id, family.wife_id].filter(Boolean);
  const nameMap = await resolvePersonNames(spouseIds);
  if (seq !== _detailSeq) return;

  const spouseLink = id => id
    ? `<a class="mini-tree-person" href="${escHtml(personHash(id))}">${escHtml(nameMap[id] || id)}</a>`
    : '<span class="mini-tree-person placeholder">—</span>';
  const surname = id => (id && (nameMap[id] || '').split(',')[0]) || '?';
  const title = `${surname(family.husband_id)} & ${surname(family.wife_id)}`;

  const facts = [];
  if (family.marriage_date || family.marriage_place) {
    facts.push(`⚭ ${[shortDate(family.marriage_date), formatGwName(family.marriage_place)].filter(Boolean).join(' · ')}`);
  }
  if (family.divorce_date) facts.push(`Divorce ${shortDate(family.divorce_date)}`);

  const childrenHtml = children.length
    ? children.map(child => {
      const person = child.person || {};
      const childId = child.person_id || person.id || '';
      const label = person.surname || person.first_name
        ? escHtml(personLabel(person.surname, person.first_name))
        : escHtml(childId || '—');
      return childId
        ? `<a class="mini-tree-person" href="${escHtml(personHash(childId))}" data-id="${escHtml(childId)}">${label}</a>`
        : `<span class="mini-tree-person placeholder">${label}</span>`;
    }).join('')
    : '<em class="text-muted">Aucun enfant enregistré.</em>';

  const panel = document.createElement('div');
  panel.id = 'family-detail-panel';
  panel.className = 'person-detail';
  panel.dataset.familyId = familyId;
  panel.innerHTML = `
    <h2 class="drawer-title" tabindex="-1">Famille ${escHtml(title)}</h2>
    ${facts.length ? `<p class="item-meta">${escHtml(facts.join(' — '))}</p>` : ''}
    <div class="drawer-section">
      <div class="mini-tree-label">Conjoints</div>
      ${spouseLink(family.husband_id)}${spouseLink(family.wife_id)}
    </div>
    <div class="drawer-section">
      <div class="mini-tree-label">Enfants (${children.length})</div>
      ${childrenHtml}
    </div>`;

  showInDrawer(panel, 'family', familyId, {
    hash: familyHash(familyId),
    label: '⚭ ' + title,
    title: 'Famille ' + title,
  });
}

// ==================== ÉVÉNEMENTS ====================
// Types courants : cases à cocher visibles dans le formulaire.
const EVENT_TYPES = [
  { value: 'birt', label: 'Naissance' },
  { value: 'deat', label: 'Décès' },
  { value: 'marr', label: 'Mariage' },
  { value: 'div',  label: 'Divorce' },
  { value: 'sep',  label: 'Séparation' },
  { value: 'bapt', label: 'Baptême' },
  { value: 'buri', label: 'Inhumation' },
  { value: 'enga', label: 'Fiançailles' },
  { value: 'pacs', label: 'PACS' },
  { value: 'oth',  label: 'Autre' },
];

// Autres types (EventType / FamilyEventType du moteur), regroupés sous « Plus de types ».
const EXTRA_EVENT_TYPES = [
  { value: 'resi', label: 'Résidence' },
  { value: 'occu', label: 'Profession' },
  { value: 'educ', label: 'Éducation' },
  { value: 'grad', label: 'Diplôme obtenu' },
  { value: 'degr', label: 'Diplôme' },
  { value: 'mser', label: 'Service militaire' },
  { value: 'mdis', label: 'Libération militaire' },
  { value: 'mpro', label: 'Promotion militaire' },
  { value: 'mobm', label: 'Mobilisation militaire' },
  { value: 'demm', label: 'Démobilisation' },
  { value: 'natu', label: 'Naturalisation' },
  { value: 'emig', label: 'Émigration' },
  { value: 'immi', label: 'Immigration' },
  { value: 'cens', label: 'Recensement' },
  { value: 'crem', label: 'Crémation' },
  { value: 'fune', label: 'Funérailles' },
  { value: 'conf', label: 'Confirmation' },
  { value: 'fcom', label: 'Première communion' },
  { value: 'ordn', label: 'Ordination' },
  { value: 'exco', label: 'Excommunication' },
  { value: 'bles', label: 'Bénédiction' },
  { value: 'barm', label: 'Bar-mitsva' },
  { value: 'basm', label: 'Bat-mitsva' },
  { value: 'circ', label: 'Circoncision' },
  { value: 'adhe', label: 'Adhésion' },
  { value: 'acco', label: 'Réalisation' },
  { value: 'acqu', label: 'Acquisition' },
  { value: 'prop', label: 'Propriété' },
  { value: 'reti', label: 'Retraite' },
  { value: 'elec', label: 'Élection' },
  { value: 'vteb', label: 'Vote' },
  { value: 'awar', label: 'Décoration' },
  { value: 'dist', label: 'Distinction' },
  { value: 'endl', label: 'Dotation' },
  { value: 'hosp', label: 'Hospitalisation' },
  { value: 'illn', label: 'Maladie' },
  { value: 'chgn', label: 'Changement de nom' },
  { value: 'will', label: 'Testament' },
  { value: 'lpas', label: 'Dernier passage' },
  { value: 'bapl', label: 'Baptême (SDJ)' },
  { value: 'conl', label: 'Confirmation (SDJ)' },
  { value: 'dotl', label: 'Dotation (SDJ)' },
  { value: 'flkl', label: 'Lien familial (SDJ)' },
  { value: 'slgc', label: 'Scellement enfant (SDJ)' },
  { value: 'slgp', label: 'Scellement parents (SDJ)' },
  { value: 'slgs', label: 'Scellement conjoints (SDJ)' },
  { value: 'anul', label: 'Annulation de mariage' },
  { value: 'marb', label: 'Bans de mariage' },
  { value: 'marc', label: 'Contrat de mariage' },
  { value: 'marl', label: 'Licence de mariage' },
  { value: 'nmar', label: 'Non marié' },
  { value: 'nmen', label: 'Sans mention' },
  { value: 'strng', label: 'Texte libre' },
  { value: 'other', label: 'Autre' },
];

const EVENT_TYPE_MAP = Object.fromEntries(
  [...EVENT_TYPES, ...EXTRA_EVENT_TYPES].map(t => [t.value, t.label])
);
const eventTypeLabel = code => EVENT_TYPE_MAP[code] || code || '?';

let eventsTable = null;

function initEventsTab() {
  const container = document.getElementById('evt-types');
  if (container) {
    const cb = t =>
      `<label><input type="checkbox" value="${escHtml(t.value)}" class="evt-type-cb"> ${escHtml(t.label)}</label>`;
    const extras = [...EXTRA_EVENT_TYPES].sort((a, b) => a.label.localeCompare(b.label, 'fr'));
    container.innerHTML = EVENT_TYPES.map(cb).join('')
      + `<details class="evt-more-types"><summary>Plus de types…</summary>`
      + `<div class="event-type-checkboxes">${extras.map(cb).join('')}</div></details>`;
  }

  const filterInputs = document.querySelectorAll('.evt-filter-input');
  filterInputs.forEach(inp => inp.addEventListener('input', checkEvtGate));
  document.querySelectorAll('.evt-type-cb').forEach(cb =>
    cb.addEventListener('change', checkEvtGate)
  );

  const btn = document.getElementById('evt-search-btn');
  if (btn) btn.addEventListener('click', runEvtSearch);

  wirePersonAutocomplete();
}

function checkEvtGate() {
  const hasType = [...document.querySelectorAll('.evt-type-cb:checked')].length > 0;
  const hasLieu = (document.getElementById('evt-lieu').value || '').trim().length > 0;
  const hasPerson = (document.getElementById('evt-person-id').value || '').trim().length > 0;
  const hasNom = (document.getElementById('evt-nom-famille').value || '').trim().length > 0;
  document.getElementById('evt-search-btn').disabled = !(hasType || hasLieu || hasPerson || hasNom);
}

// #/evenements?type=birt,deat&lieu=Paris : coche les filtres et lance la recherche.
// Sans paramètre, l'onglet garde ses filtres et son tableau.
function applyEventsRoute(params) {
  const types = (params.get('type') || '').split(',').filter(Boolean);
  const lieu = (params.get('lieu') || '').trim();
  const key = types.join(',') + '|' + lieu;
  if ((!types.length && !lieu) || key === state.evtRouteKey) return;
  state.evtRouteKey = key;
  document.querySelectorAll('.evt-type-cb').forEach(cb => { cb.checked = types.includes(cb.value); });
  const more = document.querySelector('.evt-more-types');
  if (more && more.querySelector('.evt-type-cb:checked')) more.open = true;
  document.getElementById('evt-lieu').value = lieu;
  document.getElementById('evt-person-id').value = '';
  document.getElementById('evt-person-name').value = '';
  document.getElementById('evt-nom-famille').value = '';
  checkEvtGate();
  runEvtSearch();
}

async function runEvtSearch() {
  const selectedTypes = [...document.querySelectorAll('.evt-type-cb:checked')].map(cb => cb.value);
  const lieu = (document.getElementById('evt-lieu').value || '').trim();
  const personId = (document.getElementById('evt-person-id').value || '').trim();
  const personDegree = parseInt(document.getElementById('evt-degree').value) || 1;
  const nomFamille = (document.getElementById('evt-nom-famille').value || '').trim();

  const statusEl = document.getElementById('evt-status');
  statusEl.textContent = 'Chargement…';

  if (eventsTable) { eventsTable.destroy(); eventsTable = null; }

  try {
    const filters = {
      types: selectedTypes,
      place: lieu,
      relatedTo: personId,
      degree: personDegree,
      familyName: nomFamille,
    };
    const { items, total } = await fetchEvtItems(filters);
    statusEl.textContent = total > items.length
      ? `${total} événements trouvés : seuls les ${items.length} premiers sont affichés, affinez les critères.`
      : `${items.length} événement(s) trouvé(s)`;
    buildEventsTable(items);
  } catch (err) {
    if (err.message === 'session-expired') return;
    statusEl.textContent = 'Erreur lors de la recherche.';
  }
}

// Le serveur filtre (types, lieu, personne liée + degré, nom de famille) ;
// le client ne fait que paginer les résultats déjà filtrés.
// Au-delà, on demande d'affiner plutôt que d'enchaîner des dizaines de requêtes.
const EVT_MAX_PAGES = 20;   // 20 × 100 = 2 000 événements

async function fetchEvtItems({ types, place, relatedTo, degree, familyName }) {
  const allItems = [];
  let total = 0;
  let page = 1;
  while (true) {
    const params = new URLSearchParams({ page, size: 100 });
    if (types.length) params.set('event_type', types.join(','));
    if (place) params.set('place', place);
    if (relatedTo) {
      params.set('related_to', relatedTo);
      params.set('degree', degree);
    }
    if (familyName) params.set('family_name', familyName);
    const data = await apiJson('/api/v1/events/?' + params);
    allItems.push(...data.items);
    total = data.pagination.total;
    if (!data.pagination.has_next || page >= EVT_MAX_PAGES) break;
    page++;
  }
  return { items: allItems, total };
}

function buildEventsTable(data) {
  if (eventsTable) { eventsTable.destroy(); eventsTable = null; }

  eventsTable = new Tabulator('#events-table', {
    data,
    layout: 'fitColumns',
    height: '520px',
    placeholder: 'Aucun événement ne correspond à ces critères.',
    virtualDom: true,
    rowFormatter: function(row) {
      const el = row.getElement();
      if (!el.classList.contains('row-expanded')) return;
      if (el.querySelector('.evt-row-detail')) return;
      const d = row.getData();
      const note = d.note || '';
      const sources = Array.isArray(d.sources) ? d.sources.join(' ; ') : (d.sources || '');
      const div = document.createElement('div');
      div.className = 'evt-row-detail';
      div.style.cssText = 'padding:0.4rem 0.8rem;background:var(--card-bg,#1e1e2e);border-top:1px solid var(--border,#333);font-size:0.82rem;color:var(--text,#ccc)';
      div.innerHTML =
        `<strong>Notes&nbsp;:</strong> ${escHtml(note || '—')}<br>` +
        `<strong>Sources&nbsp;:</strong> ${escHtml(sources || '—')}`;
      el.appendChild(div);
    },
    rowClick: function(e, row) {
      const el = row.getElement();
      const existing = el.querySelector('.evt-row-detail');
      if (existing) {
        existing.remove();
        el.classList.remove('row-expanded');
      } else {
        el.classList.add('row-expanded');
        row.reformat();
      }
    },
    columns: [
      {
        title: 'Type',
        field: 'event_type',
        width: 120,
        sorter: 'string',
        // Tabulator 6 : l'éditeur « select » n'existe plus, c'est « list ».
        headerFilter: 'list',
        headerFilterParams: {
          values: Object.fromEntries(
            [...new Set(data.map(d => d.event_type).filter(Boolean))]
              .map(c => [c, eventTypeLabel(c)])
              .sort((a, b) => a[1].localeCompare(b[1], 'fr'))
          ),
          clearable: true,
          placeholderEmpty: 'Aucun type',
        },
        headerFilterPlaceholder: 'Tous',
        headerFilterFunc: '=',
        formatter: cell => escHtml(eventTypeLabel(cell.getValue())),
      },
      {
        title: 'Date',
        field: 'date',
        width: 130,
        sorter: (a, b, aRow, bRow) =>
          (aRow.getData().date_sort_year || 0) - (bRow.getData().date_sort_year || 0),
        headerFilter: 'input',
        formatter: cell => escHtml(cell.getValue() || '—'),
      },
      {
        title: 'Lieu',
        field: 'place',
        minWidth: 140, widthGrow: 2,
        sorter: 'string',
        headerFilter: 'input',
        formatter: cell => escHtml(cell.getValue() || '—'),
      },
      {
        title: 'Personne / Famille',
        field: 'person_name',
        minWidth: 220, widthGrow: 3,
        sorter: 'string',
        headerFilter: 'input',
        formatter: cell => {
          const d = cell.getRow().getData();
          return escHtml(formatGwName(d.person_name || d.family_label) || '—');
        },
      },
      {
        title: 'Témoins',
        field: 'witness_names',
        minWidth: 140, widthGrow: 2,
        sorter: false,
        headerFilter: false,
        formatter: cell => escHtml((cell.getValue() || []).map(formatGwName).join(', ') || '—'),
      },
      {
        title: 'Notes',
        field: 'note',
        minWidth: 110, widthGrow: 1,
        sorter: false,
        headerFilter: false,
        formatter: cell => {
          const v = cell.getValue() || '';
          return escHtml(v.length > 60 ? v.slice(0, 60) + '…' : v || '—');
        },
      },
      {
        title: 'Sources',
        field: 'sources',
        minWidth: 110, widthGrow: 1,
        sorter: false,
        headerFilter: false,
        formatter: cell => {
          const v = (cell.getValue() || []).join(' ; ');
          return escHtml(v.length > 60 ? v.slice(0, 60) + '…' : v || '—');
        },
      },
    ],
  });
}

function wirePersonAutocomplete() {
  const nameInput = document.getElementById('evt-person-name');
  const idInput   = document.getElementById('evt-person-id');
  const dropdown  = document.getElementById('evt-person-suggestions');
  const clearBtn  = document.getElementById('evt-person-clear');
  if (!nameInput) return;

  let debounceTimer = null;
  let requestSeq = 0;   // ignore les réponses tardives
  let activeIdx = -1;

  const items = () => [...dropdown.querySelectorAll('.autocomplete-item')];
  const syncClear = () => { clearBtn.hidden = !nameInput.value; };
  const close = () => {
    dropdown.hidden = true;
    nameInput.setAttribute('aria-expanded', 'false');
    activeIdx = -1;
  };
  const open = () => {
    dropdown.hidden = false;
    nameInput.setAttribute('aria-expanded', 'true');
  };
  const setActive = idx => {
    const list = items();
    list.forEach(el => el.classList.remove('active'));
    activeIdx = list.length ? (idx + list.length) % list.length : -1;
    if (activeIdx >= 0) {
      list[activeIdx].classList.add('active');
      list[activeIdx].scrollIntoView({ block: 'nearest' });
    }
  };
  const choose = el => {
    nameInput.value = el.dataset.label;
    idInput.value = el.dataset.id;
    syncClear();
    close();
    checkEvtGate();
  };

  nameInput.addEventListener('input', () => {
    idInput.value = '';
    syncClear();
    checkEvtGate();
    clearTimeout(debounceTimer);
    const q = nameInput.value.trim();
    if (q.length < 2) { requestSeq++; close(); return; }
    debounceTimer = setTimeout(async () => {
      const seq = ++requestSeq;
      try {
        const data = await apiJson(`/api/v1/persons/?query=${encodeURIComponent(q)}&size=10`);
        if (seq !== requestSeq) return;
        const found = data.items || [];
        if (!found.length) {
          dropdown.innerHTML = '<div class="autocomplete-empty">Aucune personne trouvée</div>';
          open();
          return;
        }
        dropdown.innerHTML = found.map(p => {
          const label = formatGwName(`${p.first_name || ''} ${p.surname || ''}`) || p.id;
          const dates = [p.birth_date, p.death_date].filter(Boolean).join(' – ');
          return `<div class="autocomplete-item" role="option" data-id="${escHtml(p.id)}" data-label="${escHtml(label)}">`
            + `${escHtml(label)}${dates ? `<span class="ac-dates">${escHtml(dates)}</span>` : ''}</div>`;
        }).join('');
        items().forEach(el => el.addEventListener('mousedown', e => {
          e.preventDefault();
          choose(el);
        }));
        open();
        setActive(0);
      } catch (err) {
        if (seq === requestSeq) close();
      }
    }, 250);
  });

  nameInput.addEventListener('keydown', e => {
    if (dropdown.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive(activeIdx + 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(activeIdx - 1); }
    else if (e.key === 'Enter' && activeIdx >= 0) { e.preventDefault(); choose(items()[activeIdx]); }
    else if (e.key === 'Escape') { close(); }
  });

  clearBtn.addEventListener('click', () => {
    nameInput.value = '';
    idInput.value = '';
    requestSeq++;
    syncClear();
    close();
    checkEvtGate();
    nameInput.focus();
  });

  nameInput.addEventListener('blur', () => { setTimeout(close, 150); });
}

// ==================== STATS ====================
function renderStats() {
  const container = document.getElementById('stats-content');
  if (!container) return;

  if (!state.stats) {
    container.innerHTML = '<p>Chargement…</p>';
    return;
  }

  const s = state.stats;

  const cards = [
    { value: s.total_persons,                                          label: 'Personnes' },
    { value: s.total_families,                                         label: 'Familles' },
    { value: s.total_events,                                           label: 'Événements' },
    { value: s.persons_with_birth_date || 0,                           label: 'Avec date de naissance' },
    { value: s.families_with_children || 0,                            label: 'Familles avec enfants' },
    { value: (s.average_children_per_family || 0).toFixed(1),          label: 'Enfants / famille (moy.)' },
  ];

  const gridHtml = `<div class="stats-grid">${
    cards.map(c =>
      `<div class="stat-card">
        <div class="stat-value">${escHtml(String(c.value))}</div>
        <div class="stat-label">${escHtml(c.label)}</div>
      </div>`
    ).join('')
  }</div>`;

  const adv = s.advanced || {};
  const charts = [
    decadeChart(adv.births_by_decade || {}),
    barCard('Patronymes les plus portés', 'personnes',
      (adv.top_surnames || []).map(r => ({
        label: formatGwName(r.surname), count: r.count,
        href: personsListHash(1, '', { nom: r.surname }),
      }))),
    barCard('Lieux de naissance les plus fréquents', 'naissances',
      ((adv.geography || {}).top_birth_places || []).map(r => ({
        label: formatGwName(r.place), count: r.count,
        href: personsListHash(1, '', { lieu: r.place }),
      }))),
    barCard('Événements par type', 'événements',
      Object.entries(s.events_by_type || {})
        .sort((a, b) => b[1] - a[1])
        .map(([code, count]) => ({
          label: eventTypeLabel(code), count,
          href: EVENT_TYPE_MAP[code] ? '#/evenements?type=' + encodeURIComponent(code) : null,
        })), 'Un clic ouvre les événements de ce type.'),
    coverageCard(adv.coverage),
  ].filter(Boolean).join('');

  container.innerHTML = gridHtml + `<div class="charts-grid">${charts}</div>`;
}

const fmtInt = n => Number(n || 0).toLocaleString('fr-FR');

// Histogramme des naissances : une colonne par décennie, décennies vides comprises
// (l'axe du temps reste régulier). Un clic liste les personnes nées dans la décennie.
function decadeChart(byDecade) {
  const decades = Object.keys(byDecade).map(Number).sort((a, b) => a - b);
  if (!decades.length) return '';
  const first = decades[0];
  const last = decades[decades.length - 1];
  const cols = [];
  for (let d = first; d <= last; d += 10) cols.push({ decade: d, count: byDecade[String(d)] || 0 });
  const max = Math.max(...cols.map(c => c.count));
  const total = cols.reduce((sum, c) => sum + c.count, 0);
  // Étiquettes de l'axe : chaque décennie si peu nombreuses, sinon les demi-siècles.
  const step = cols.length <= 12 ? 10 : cols.length <= 30 ? 50 : 100;
  const bars = cols.map(c => {
    const tip = `${c.decade}–${c.decade + 9} : ${fmtInt(c.count)} naissance${c.count > 1 ? 's' : ''}`;
    const h = c.count ? Math.max(2, Math.round((c.count / max) * 100)) : 0;
    const label = c.decade % step === 0 || cols.length === 1 ? `<span class="col-tick">${c.decade}</span>` : '';
    const bar = `<span class="col-bar" style="height:${h}%"></span>${label}`;
    return c.count
      ? `<a class="col" href="${escHtml(personsListHash(1, '', { ne: `${c.decade}-${c.decade + 9}` }))}" data-tip="${escHtml(tip)}" aria-label="${escHtml(tip)}">${bar}</a>`
      : `<span class="col is-empty" data-tip="${escHtml(tip)}">${bar}</span>`;
  }).join('');
  return `<section class="chart-card chart-wide">
    <h3>Naissances par décennie</h3>
    <p class="chart-sub">${fmtInt(total)} naissances datées, de ${first} à ${last + 9}. Un clic liste les personnes nées dans la décennie.</p>
    <div class="col-chart" style="--cols:${cols.length}">${bars}</div>
  </section>`;
}

// Barres horizontales triées : libellé et effectif toujours lisibles (pas de couleur seule).
function barCard(title, unit, rows, sub = 'Un clic ouvre la liste des personnes correspondantes.') {
  if (!rows.length) return '';
  const max = Math.max(...rows.map(r => r.count));
  const items = rows.map(r => {
    const inner = `<span class="hbar-label">${escHtml(r.label || '—')}</span>`
      + `<span class="hbar-track"><span class="hbar-fill" style="width:${Math.max(1, (r.count / max) * 100)}%"></span></span>`
      + `<span class="hbar-value">${fmtInt(r.count)}</span>`;
    const tip = `${r.label} : ${fmtInt(r.count)} ${unit}`;
    return r.href
      ? `<li><a class="hbar" href="${escHtml(r.href)}" title="${escHtml(tip)}">${inner}</a></li>`
      : `<li><span class="hbar" title="${escHtml(tip)}">${inner}</span></li>`;
  }).join('');
  return `<section class="chart-card">
    <h3>${escHtml(title)}</h3>
    <p class="chart-sub">${escHtml(sub)}</p>
    <ol class="hbar-list">${items}</ol>
  </section>`;
}

// Part des personnes renseignées : ce qui reste à documenter dans la base.
function coverageCard(cov) {
  if (!cov || !cov.persons) return '';
  const rows = [
    ['Date de naissance', cov.with_birth_date],
    ['Lieu de naissance', cov.with_birth_place],
    ['Date de décès', cov.with_death_date],
    ['Profession', cov.with_occupation],
    ['Au moins une source', cov.with_source],
  ];
  const items = rows.map(([label, n]) => {
    const pct = Math.round((n / cov.persons) * 100);
    return `<li class="hbar" title="${escHtml(`${label} : ${fmtInt(n)} / ${fmtInt(cov.persons)}`)}">`
      + `<span class="hbar-label">${escHtml(label)}</span>`
      + `<span class="hbar-track"><span class="hbar-fill" style="width:${pct}%"></span></span>`
      + `<span class="hbar-value">${pct} %</span></li>`;
  }).join('');
  return `<section class="chart-card">
    <h3>Complétude de la base</h3>
    <p class="chart-sub">Part des ${fmtInt(cov.persons)} personnes pour qui l'information est renseignée.</p>
    <ul class="hbar-list">${items}</ul>
  </section>`;
}

// ==================== EXPORT ====================
const EXPORT_EXT = { gedcom: 'ged', json: 'json', xml: 'xml' };

async function downloadExport(format) {
  const errorEl = document.getElementById('export-error');
  errorEl.style.display = 'none';
  try {
    const res = await apiFetch('/api/v1/genealogy/export/' + format);
    if (!res.ok) {
      errorEl.textContent = "Erreur lors de la génération de l'export.";
      errorEl.style.display = '';
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'genealogie.' + EXPORT_EXT[format];
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    if (err.message === 'session-expired') return;
    errorEl.textContent = 'Erreur lors du téléchargement.';
    errorEl.style.display = '';
  }
}

function wireExportTab() {
  document.getElementById('btn-export-gedcom').addEventListener('click', () => downloadExport('gedcom'));
  document.getElementById('btn-export-json').addEventListener('click', () => downloadExport('json'));
  document.getElementById('btn-export-xml').addEventListener('click', () => downloadExport('xml'));
}
