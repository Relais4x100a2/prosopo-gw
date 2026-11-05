'use strict';

// ==================== STATE ====================
const state = {
  token: sessionStorage.getItem('gwToken') || null,
  // Échéance de la session en millisecondes, horloge locale : recalculée à partir du
  // temps restant renvoyé par le serveur (pas de dépendance à l'heure du poste).
  expiresAt: Number(sessionStorage.getItem('gwExpiresAt')) || null,
  stats: null,
  persons: { items: [], page: 1, pages: 1, query: '', filters: {}, loaded: false },
  families: { items: [], page: 1, pages: 1, query: '', nameMap: {}, loaded: false },
  organizations: { items: [], page: 1, pages: 1, total: 0, sort: 'persons', type: '', named_from: '', q: '', loaded: false },
  experiences: { loaded: false, undated: 0 },
  expCount: null,
  civilTotal: 0,
  unmatchedLoaded: false,
  orgCount: null,
  ignoredWords: null,   // mots ignorés de la session (null : pas encore synchronisés)
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
  // Chaque requête prolonge la session : le serveur renvoie le temps restant.
  const left = res.headers.get(SESSION_EXPIRES_IN_HEADER);
  if (left !== null && state.token) setSessionExpiry(Number(left));
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
  sessionStorage.setItem('gwToken', state.token);
  setSessionExpiry(data.expires_in);
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

// Synchronisation en cours des mots ignorés (voir syncIgnoredWords).
let _ignoredSync = null;

function clearSession() {
  state.token = null;
  state.nameCache.clear();
  resetLoadedData();
  state.expiresAt = null;
  sessionStorage.removeItem('gwToken');
  sessionStorage.removeItem('gwExpiresAt');
  if (_timerInterval) { clearInterval(_timerInterval); _timerInterval = null; }
  hideSessionBanner();
  showLanding();
}

// Une nouvelle session ne doit rien afficher de la précédente.
function resetLoadedData() {
  state.persons = { items: [], page: 1, pages: 1, query: '', filters: {}, loaded: false };
  state.evtRouteKey = '';
  state.families = { items: [], page: 1, pages: 1, query: '', nameMap: {}, loaded: false };
  state.organizations = { items: [], page: 1, pages: 1, total: 0, sort: 'persons', type: '', named_from: '', q: '', loaded: false };
  _orgsSeq++;   // une réponse de la session précédente est ignorée
  _expSeq++;
  state.experiences = { loaded: false, undated: 0 };
  state.expCount = null;
  state.civilTotal = 0;
  state.unmatchedLoaded = false;
  state.orgCount = null;
  state.ignoredWords = null;
  _ignoredSync = null;
  state.lastRoute = {};
  for (const id of ['exp-list', 'orgs-list', 'orgs-unmatched-body']) {
    const el = document.getElementById(id);
    if (el) el.innerHTML = '';
  }
  for (const id of ['exp-count', 'orgs-count']) {
    const el = document.getElementById(id);
    if (el) el.textContent = '0';
  }
  const excluded = document.getElementById('orgs-excluded-info');
  if (excluded) excluded.textContent = '';
  closeDetail();
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
}

// Session expirée (compte à rebours à zéro ou 401) : écran dédié, données oubliées.
function handleExpiry() {
  if (!state.token) return;
  const token = state.token;
  clearSession();
  // Le serveur a pu garder la session quelques secondes de plus : on la supprime.
  fetch(`/api/v1/sessions/${token}`, { method: 'DELETE', headers: { 'X-Session-Token': token } })
    .catch(() => {});
  showExpired();
}

// ==================== VIEWS ====================
function showView(id) {
  for (const v of ['view-landing', 'view-app', 'view-expired']) {
    document.getElementById(v).style.display = v === id ? '' : 'none';
  }
}

function showLanding() { showView('view-landing'); }

function showApp() { showView('view-app'); }

function showExpired() {
  showView('view-expired');
  document.getElementById('expired-title').focus();
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
  wireOrganizationsTab();
  initEventsTab();
  wireExportTab();
  wireDrawer();
  window.addEventListener('hashchange', applyRoute);

  if (state.token) {
    try {
      await enterApp();
    } catch {
      // Une session expirée a déjà basculé sur l'écran dédié (handleExpiry).
      if (state.token) clearSession();
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
  document.getElementById('session-extend').addEventListener('click', extendSession);
  // « Recharger le fichier » : retour à l'accueil, sélecteur ouvert (geste de l'utilisateur).
  document.getElementById('expired-reload').addEventListener('click', () => {
    hideUploadError();
    showLanding();
    document.getElementById('file-input').click();
  });
  document.getElementById('expired-home').addEventListener('click', () => {
    hideUploadError();
    showLanding();
    document.getElementById('drop-zone').focus();
  });
}

// ==================== NAVBAR ====================
async function loadStats() {
  const data = await apiJson('/api/v1/genealogy/stats');
  state.stats = data.data;
  document.getElementById('nav-stats').textContent =
    `${state.stats.total_persons} personnes · ${state.stats.total_families} familles`;
}

// ==================== EXPIRATION DE LA SESSION ====================
const SESSION_EXPIRES_IN_HEADER = 'X-Session-Expires-In';
const SESSION_WARN_MS = 5 * 60 * 1000;   // bandeau « Prolonger » 5 min avant la fin
const TIMER_TICK_MS = 5000;

let _timerInterval = null;

function setSessionExpiry(secondsLeft) {
  if (!Number.isFinite(secondsLeft)) return;
  state.expiresAt = Date.now() + secondsLeft * 1000;
  sessionStorage.setItem('gwExpiresAt', String(state.expiresAt));
  if (_timerInterval) updateTimer();
}

function startTimer() {
  if (_timerInterval) clearInterval(_timerInterval);
  _timerInterval = setInterval(updateTimer, TIMER_TICK_MS);
  updateTimer();
}

function minutesLabel(ms) {
  const min = Math.ceil(ms / 60000);
  return min <= 1 ? 'moins d’une minute' : `${min} minutes`;
}

function updateTimer() {
  if (!state.token || !state.expiresAt) return;
  const remaining = state.expiresAt - Date.now();
  if (remaining <= 0) { handleExpiry(); return; }
  // Minutes arrondies au-dessus, comme dans le bandeau : « 5 min » tant qu'il en reste plus de 4.
  const total = Math.ceil(remaining / 60000);
  const h = Math.floor(total / 60);
  const m = total % 60;
  const timer = document.getElementById('nav-timer');
  timer.textContent = '⏱ ' + (h > 0 ? `${h} h${m ? ' ' + String(m).padStart(2, '0') : ''}` : `${m} min`);
  timer.title = 'Temps restant avant l’effacement de la session (prolongé à chaque action)';
  const warn = remaining <= SESSION_WARN_MS;
  timer.classList.toggle('timer-warn', warn);
  if (warn) showSessionBanner(remaining); else hideSessionBanner();
}

function showSessionBanner(remaining) {
  const banner = document.getElementById('session-banner');
  const text = `Votre session expire dans ${minutesLabel(remaining)} : vos données seront alors effacées du serveur.`;
  const msg = document.getElementById('session-banner-text');
  // Ne réécrire le texte que s'il change : un lecteur d'écran ne le relit pas toutes les 5 s.
  if (msg.textContent !== text) msg.textContent = text;
  banner.hidden = false;
}

function hideSessionBanner() {
  const banner = document.getElementById('session-banner');
  if (banner) banner.hidden = true;
}

async function extendSession() {
  const btn = document.getElementById('session-extend');
  btn.disabled = true;
  try {
    const data = await apiJson('/api/v1/sessions/refresh', { method: 'POST' });
    setSessionExpiry(data.expires_in);
  } catch (err) {
    if (err.message !== 'session-expired') {
      document.getElementById('session-banner-text').textContent =
        'Impossible de prolonger la session pour le moment. Réessayez.';
    }
  } finally {
    btn.disabled = false;
  }
}

// ==================== TABS ====================
// Onglets accessibles (motif ARIA « tabs ») : un seul onglet dans l'ordre de tabulation,
// ←/→ passent à l'onglet voisin, Début/Fin au premier/dernier ; l'onglet atteint s'ouvre.
function openTab(name) {
  navigate(state.lastRoute[name] || '#/' + TAB_ROUTES[name]);
}

function wireTabs() {
  const tabs = [...document.querySelectorAll('.pgw-tab')];
  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => openTab(tab.dataset.tab));
    tab.addEventListener('keydown', (e) => {
      const target = {
        ArrowRight: tabs[(i + 1) % tabs.length],
        ArrowLeft: tabs[(i - 1 + tabs.length) % tabs.length],
        Home: tabs[0],
        End: tabs[tabs.length - 1],
      }[e.key];
      if (!target) return;
      e.preventDefault();
      target.focus();
      openTab(target.dataset.tab);
    });
  });
}

function showTab(name) {
  document.querySelectorAll('.pgw-tab').forEach(t => {
    const on = t.dataset.tab === name;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `panel-${name}`));
  if (name === 'stats') renderStats();
}

// ==================== ROUTAGE (hash) ====================
// L'adresse décrit la vue : retour/avant du navigateur, rechargement et liens partagés.
//   #/personnes?q=…&page=N   #/personne/<id>
//   #/familles?page=N        #/famille/<id>
//   #/evenements   #/stats   #/export
//   #/organisations?sort=…&type=…&source=…&q=…&page=N   #/organisation/<id>
// Les clics ne font que changer l'adresse ; applyRoute() est le seul à afficher.
const ROUTE_TABS = {
  personnes: 'persons', personne: 'persons',
  familles: 'families', famille: 'families',
  evenements: 'events', stats: 'stats', export: 'export',
  organisations: 'organizations', organisation: 'organizations',
};
const TAB_ROUTES = {
  persons: 'personnes', families: 'familles', events: 'evenements', organizations: 'organisations', stats: 'stats', export: 'export',
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
  const known = name in ROUTE_TABS && (id !== null) === (name === 'personne' || name === 'famille' || name === 'organisation');
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
function familiesListHash(page = state.families.page, query = state.families.query) {
  const p = new URLSearchParams();
  if (query) p.set('q', query);
  if (page > 1) p.set('page', page);
  const qs = p.toString();
  return '#/familles' + (qs ? '?' + qs : '');
}
const personHash = id => '#/personne/' + encodeURIComponent(id);
const familyHash = id => '#/famille/' + encodeURIComponent(id);
const organizationHash = id => '#/organisation/' + encodeURIComponent(id);

// filters : { sort, type, named_from, q } ; les valeurs par défaut restent hors de l'adresse.
function organizationsListHash(page = state.organizations.page, filters = state.organizations) {
  const p = new URLSearchParams();
  if (filters.q) p.set('q', filters.q);
  if (filters.sort && filters.sort !== 'persons') p.set('sort', filters.sort);
  if (filters.type) p.set('type', filters.type);
  if (filters.named_from) p.set('source', filters.named_from);
  if (page > 1) p.set('page', page);
  const qs = p.toString();
  return '#/organisations' + (qs ? '?' + qs : '');
}

// replace : remplace l'entrée d'historique courante (frappe dans une recherche)
// au lieu d'en empiler une par lettre.
function navigate(hash, { replace = false } = {}) {
  if (location.hash === hash) applyRoute();   // même adresse : pas de hashchange
  else if (replace) location.replace(hash);
  else location.hash = hash;
}

// Champ de recherche à la frappe, après une courte pause (300 ms), dès 2 caractères
// (ou vide : liste complète). Entrée lance aussitôt. La première frappe crée une
// entrée d'historique ; les suivantes la remplacent, donc « retour » revient à la liste
// d'avant la recherche, pas à chaque lettre.
const SEARCH_DEBOUNCE_MS = 300;
const SEARCH_MIN_CHARS = 2;

function wireInstantSearch(input, hashFor, currentQuery) {
  let timer = null;
  const run = (immediate) => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q === currentQuery()) return;
    if (!immediate && q && q.length < SEARCH_MIN_CHARS) return;
    navigate(hashFor(q), { replace: !!currentQuery() && !!q });
  };
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => run(false), SEARCH_DEBOUNCE_MS);
  });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') run(true); });
  return run;
}

// Ne réécrit le champ que si l'adresse dit autre chose (évite d'effacer l'espace
// final que l'utilisateur est en train de taper).
function syncSearchInput(id, query) {
  const input = document.getElementById(id);
  if (input.value.trim() !== query) input.value = query;
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
      syncSearchInput('persons-search', query);
      if (!state.persons.loaded || state.persons.query !== query || state.persons.page !== page
          || !sameFilters(state.persons.filters, filters)) {
        await loadPersons(page, query, filters);
      }
    } else if (route.name === 'personne') {
      if (!state.persons.loaded) await loadPersons(1, '', {});
      if (seq === _routeSeq) await openPersonDetail(route.id);
    } else if (route.name === 'familles') {
      const query = route.params.get('q') || '';
      const page = pageParam(route.params);
      closeDetail();
      syncSearchInput('families-search', query);
      if (!state.families.loaded || state.families.page !== page || state.families.query !== query) {
        await loadFamilies(page, query);
      }
    } else if (route.name === 'famille') {
      if (!state.families.loaded) await loadFamilies(1, '');
      if (seq === _routeSeq) await openFamilyDetail(route.id);
    } else if (route.name === 'organisations') {
      await applyOrganizationsRoute(route.params);
    } else if (route.name === 'organisation') {
      if (!state.organizations.loaded) await loadOrganizations();
      loadUnmatched();
      if (!state.experiences.loaded) loadSharedExperiences().catch(() => {});
      if (seq === _routeSeq) await openOrganizationDetail(route.id);
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

  const search = wireInstantSearch(searchInput, q => personsListHash(1, q), () => state.persons.query);
  searchBtn.addEventListener('click', () => search(true));

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
  for (const [listId, kind] of [['persons-list', 'person'], ['families-list', 'family'], ['orgs-list', 'organization']]) {
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
  const tab = parseRoute().tab;
  navigate(tab === 'families' ? familiesListHash()
    : tab === 'organizations' ? organizationsListHash() : personsListHash());
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

  let personResp, familiesResp, eventsResp;
  try {
    [personResp, familiesResp, eventsResp] = await Promise.all([
      apiJson('/api/v1/persons/' + encodeURIComponent(personId)),
      apiJson('/api/v1/persons/' + encodeURIComponent(personId) + '/families'),
      // La frise est un complément : son échec n'empêche pas d'afficher la fiche.
      apiJson(personEventsPath(personId)).catch(err => {
        if (err.message === 'session-expired') throw err;
        return null;
      }),
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
  panel.append(buildTimelineSection(person, myId, unions, nameMap, eventsResp));
  const notes = buildNotesSection(person);
  if (notes) panel.append(notes);

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

// ==================== FRISE DE LA FICHE PERSONNE ====================
const TIMELINE_MAX_EVENTS = 100;   // une page de l'API ; au-delà, lien vers l'onglet Événements

function personEventsPath(personId) {
  const params = new URLSearchParams({ related_to: personId, degree: '1', size: String(TIMELINE_MAX_EVENTS) });
  return '/api/v1/events/?' + params;
}

function personEventsHash(personId) {
  return '#/evenements?' + new URLSearchParams({ personne: personId, degre: '1' });
}

// Ordre dans une même année : la naissance avant tout, le décès et l'inhumation en dernier.
const TIMELINE_RANK = { birt: 0, bapt: 1, deat: 8, buri: 9, crem: 9 };

function eventYear(date) {
  const m = String(date || '').match(/(\d{4})/);
  return m ? Number(m[1]) : null;
}

// Événements de la personne elle-même et de ses unions, triés par date.
// Les dates portées par la fiche (naissance, baptême, décès, inhumation) complètent
// les événements explicites sans les dupliquer.
function timelineEntries(person, myId, unions, nameMap, events) {
  const partnerOf = new Map(unions.map(u => [u.familyId, u.partnerId]));
  const entries = [];
  for (const e of events) {
    if (e.person_id === myId) {
      entries.push({ code: e.event_type, custom: e.custom_type, date: e.date, place: e.place, note: e.note, sources: e.sources });
    } else if (e.family_id && partnerOf.has(e.family_id)) {
      const partnerId = partnerOf.get(e.family_id);
      entries.push({
        code: e.event_type, custom: e.custom_type, date: e.date, place: e.place, note: e.note, sources: e.sources,
        withLabel: partnerId ? 'avec ' + (nameMap[partnerId] || partnerId) : '',
        href: familyHash(e.family_id),
      });
    }
  }
  const seen = new Set(entries.map(x => x.code));
  for (const [code, date, place, extra] of [
    ['birt', person.birth_date, person.birth_place],
    ['bapt', person.baptism_date, person.baptism_place],
    ['deat', person.death_date, person.death_place, person.death_cause],
    ['buri', person.burial_date, person.burial_place],
  ]) {
    if ((date || place) && !seen.has(code)) entries.push({ code, date, place, note: extra });
  }
  entries.forEach((x, i) => { x.year = eventYear(x.date); x.i = i; });
  return entries.sort((a, b) =>
    (a.year ?? Infinity) - (b.year ?? Infinity)
    || (TIMELINE_RANK[a.code] ?? 5) - (TIMELINE_RANK[b.code] ?? 5)
    || a.i - b.i);
}

function buildTimelineSection(person, myId, unions, nameMap, eventsResp) {
  const section = document.createElement('div');
  section.className = 'drawer-section';
  const events = (eventsResp && eventsResp.items) || [];
  const entries = timelineEntries(person, myId, unions, nameMap, events);
  const more = eventsResp && eventsResp.pagination && eventsResp.pagination.has_next;

  const items = entries.map(x => {
    const year = x.year != null ? String(x.year) : '?';
    const fullDate = x.date && String(x.date) !== year ? String(x.date) : '';
    const what = escHtml(x.custom ? formatGwName(x.custom) : eventTypeLabel(x.code)) + (x.withLabel ? ' ' + escHtml(x.withLabel) : '');
    const meta = [fullDate, formatGwName(x.place)].filter(Boolean).join(' · ');
    const srcs = (x.sources || []).map(formatGwName).filter(Boolean);
    return `<li class="tl-item"><span class="tl-year">${escHtml(year)}</span><div class="tl-body">`
      + (x.href ? `<a href="${escHtml(x.href)}">${what}</a>` : `<span class="tl-what">${what}</span>`)
      + (meta ? `<span class="item-meta">${escHtml(meta)}</span>` : '')
      + (x.note ? `<span class="tl-note">${escHtml(x.note)}</span>` : '')
      + (srcs.length ? `<span class="tl-note">Source : ${escHtml(srcs.join(' ; '))}</span>` : '')
      + '</div></li>';
  }).join('');

  section.innerHTML = '<div class="mini-tree-label">Chronologie</div>'
    + (items ? `<ol class="timeline">${items}</ol>` : '<p class="text-muted tl-empty">Aucun événement connu.</p>')
    + (eventsResp ? '' : '<p class="text-muted tl-empty">Les événements n’ont pas pu être chargés.</p>')
    + (more ? '<p class="text-muted tl-empty">Frise limitée aux 100 premiers événements liés.</p>' : '')
    + `<a class="tl-more" href="${escHtml(personEventsHash(myId))}">Voir dans Événements →</a>`;
  return section;
}

// Notes et sources de la fiche, repliées par défaut (elles peuvent être longues).
function buildNotesSection(person) {
  const notes = (person.notes || []).filter(n => n && String(n).trim());
  const sources = (person.sources || []).filter(s => s && String(s).trim());
  if (!notes.length && !sources.length) return null;
  const section = document.createElement('div');
  section.className = 'drawer-section';
  let html = '';
  if (notes.length) {
    html += `<details class="drawer-details"><summary>Notes (${notes.length})</summary>`
      + notes.map(n => `<p class="drawer-note">${escHtml(n)}</p>`).join('') + '</details>';
  }
  if (sources.length) {
    html += `<details class="drawer-details"><summary>Sources (${sources.length})</summary><ul>`
      + sources.map(s => `<li>${escHtml(formatGwName(s))}</li>`).join('') + '</ul></details>';
  }
  section.innerHTML = html;
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
  const searchInput = document.getElementById('families-search');
  const search = wireInstantSearch(searchInput, q => familiesListHash(1, q), () => state.families.query);
  document.getElementById('families-search-btn').addEventListener('click', () => search(true));
  document.getElementById('families-clear-btn').addEventListener('click', () => {
    searchInput.value = '';
    navigate(familiesListHash(1, ''));
  });
  document.getElementById('families-prev').addEventListener('click', () => {
    navigate(familiesListHash(state.families.page - 1));
  });
  document.getElementById('families-next').addEventListener('click', () => {
    navigate(familiesListHash(state.families.page + 1));
  });
}

async function loadFamilies(page, query = '') {
  const seq = ++_familiesSeq;
  const params = new URLSearchParams({ page, size: 50 });
  if (query) params.set('query', query);
  const url = '/api/v1/families/?' + params;
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
  state.families.query = query;
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
    const q = state.families.query;
    list.innerHTML = `<p class="text-muted list-empty">${q
      ? `Aucune famille ne correspond à « ${escHtml(q)} ».`
      : 'Aucune famille trouvée.'}</p>`;
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
  { value: 'other', label: 'Autre (famille)' },
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

// #/evenements?type=birt,deat&lieu=Paris&personne=ID&degre=1 : pose les filtres et lance
// la recherche. Sans paramètre, l'onglet garde ses filtres et son tableau.
function applyEventsRoute(params) {
  const types = (params.get('type') || '').split(',').filter(Boolean);
  const lieu = (params.get('lieu') || '').trim();
  const personne = (params.get('personne') || '').trim();
  const degre = ['1', '2', '3'].includes(params.get('degre')) ? params.get('degre') : '1';
  const key = [types.join(','), lieu, personne, degre].join('|');
  if ((!types.length && !lieu && !personne) || key === state.evtRouteKey) return;
  state.evtRouteKey = key;
  document.querySelectorAll('.evt-type-cb').forEach(cb => { cb.checked = types.includes(cb.value); });
  const more = document.querySelector('.evt-more-types');
  if (more && more.querySelector('.evt-type-cb:checked')) more.open = true;
  document.getElementById('evt-lieu').value = lieu;
  setEvtPerson(personne);
  document.getElementById('evt-degree').value = degre;
  document.getElementById('evt-nom-famille').value = '';
  checkEvtGate();
  runEvtSearch();
}

function setEvtPerson(personId) {
  const idInput = document.getElementById('evt-person-id');
  const nameInput = document.getElementById('evt-person-name');
  idInput.value = personId;
  nameInput.value = personId ? formatGwName(state.nameCache.get(personId) || personId) : '';
  document.getElementById('evt-person-clear').hidden = !personId;
  if (personId && !state.nameCache.has(personId)) {
    resolvePersonNames([personId]).then(map => {
      if (idInput.value === personId) nameInput.value = map[personId] || personId;
    }).catch(() => {});
  }
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
        // Tag libre d'un événement « Autre » (#Capitaine_de_navire…).
        title: 'Nom personnalisé',
        field: 'custom_type',
        width: 170,
        sorter: 'string',
        visible: data.some(d => d.custom_type),
        headerFilter: 'input',
        headerFilterFunc: (term, value) =>
          formatGwName(value || '').toLowerCase().includes(String(term).toLowerCase()),
        formatter: cell => escHtml(cell.getValue() ? formatGwName(cell.getValue()) : ''),
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

// ==================== ORGANISATIONS ====================
const ORG_TYPE_LABELS = {
  company: 'Entreprise', school: 'École', association: 'Association',
  institution: 'Institution', religious: 'Religieux', military: 'Militaire', other: 'Autre',
};
// Origine du nom proposé.
const NAMED_FROM_LABELS = {
  tag: 'Nom personnalisé', place: 'Lieu', typed_event: 'Événement typé', occupation_text: 'Profession',
  address: 'Adresse',
};
// Types d'événements à l'origine d'un candidat.
const SOURCE_LABELS = {
  oth: 'événement libre', occu: 'profession', educ: 'éducation', grad: 'diplôme', degr: 'diplôme',
  adhe: 'adhésion', hosp: 'hospitalisation', mser: 'service militaire', demm: 'service militaire',
  elec: 'élection', ordn: 'ordination', occu_attr: 'profession (attribut)',
};
let _orgsSeq = 0;
let _expSeq = 0;

function wireOrganizationsTab() {
  const orgsSearch = document.getElementById('orgs-search');
  const withFilters = patch => organizationsListHash(1, { ...state.organizations, ...patch });

  wireInstantSearch(orgsSearch, q => withFilters({ q }), () => state.organizations.q);
  document.getElementById('orgs-sort').addEventListener('change', e => navigate(withFilters({ sort: e.target.value })));
  document.getElementById('orgs-type').addEventListener('change', e => navigate(withFilters({ type: e.target.value })));
  document.getElementById('orgs-source').addEventListener('change', e => navigate(withFilters({ named_from: e.target.value })));
  document.getElementById('orgs-clear-btn').addEventListener('click', () => {
    orgsSearch.value = '';
    navigate(organizationsListHash(1, {}));
  });
  document.getElementById('orgs-ignored-form').addEventListener('submit', e => {
    e.preventDefault();
    const input = document.getElementById('orgs-ignored-input');
    const word = input.value.trim();
    if (!word) return;
    setIgnoredWords([...(state.ignoredWords || []), word]).then(ok => { if (ok) input.value = ''; });
  });
  document.getElementById('orgs-prev').addEventListener('click',
    () => navigate(organizationsListHash(state.organizations.page - 1)));
  document.getElementById('orgs-next').addEventListener('click',
    () => navigate(organizationsListHash(state.organizations.page + 1)));
}

async function applyOrganizationsRoute(params) {
  const want = {
    sort: ['persons', 'period', 'name'].includes(params.get('sort')) ? params.get('sort') : 'persons',
    type: params.get('type') || '',
    named_from: params.get('source') || '',
    q: (params.get('q') || '').trim(),
  };
  const page = pageParam(params);
  const o = state.organizations;
  closeDetail();
  syncSearchInput('orgs-search', want.q);
  document.getElementById('orgs-sort').value = want.sort;
  document.getElementById('orgs-type').value = want.type;
  document.getElementById('orgs-source').value = want.named_from;
  await syncIgnoredWords();
  loadUnmatched();
  const expReady = state.experiences.loaded
    ? Promise.resolve() : loadSharedExperiences().catch(() => {});
  if (params.get('section') === 'experiences') {
    // Lien de la carte Stats : défiler jusqu'aux expériences une fois la section remplie.
    expReady.then(() => {
      const section = document.getElementById('exp-section');
      if (section) section.scrollIntoView({ block: 'start' });
    });
  }
  if (!o.loaded || o.page !== page || o.sort !== want.sort || o.type !== want.type
      || o.named_from !== want.named_from || o.q !== want.q) {
    Object.assign(o, want);
    await loadOrganizations(page);
  }
}

async function loadOrganizations(page = state.organizations.page) {
  const seq = ++_orgsSeq;
  const o = state.organizations;
  const params = new URLSearchParams({ page, size: 20, sort: o.sort });
  if (o.type) params.set('type', o.type);
  if (o.named_from) params.set('named_from', o.named_from);
  if (o.q) params.set('q', o.q);
  let data;
  try {
    data = await apiJson('/api/v1/organizations/candidates?' + params);
  } catch (err) {
    if (seq === _orgsSeq) {
      document.getElementById('orgs-list').innerHTML =
        '<p class="alert-pgw error">Impossible de charger les organisations.</p>';
    }
    throw err;
  }
  if (seq !== _orgsSeq) return;
  o.loaded = true;
  o.items = data.items;
  o.page = data.pagination.page;
  o.pages = data.pagination.pages;
  o.total = data.pagination.total;
  // Le titre donne le nombre d'organisations, pas celui de la recherche en cours.
  if (!o.type && !o.named_from && !o.q) state.orgCount = o.total;
  document.getElementById('orgs-count').textContent = fmtInt(state.orgCount ?? o.total);
  renderOrganizations();
  document.getElementById('orgs-prev').disabled = !data.pagination.has_prev;
  document.getElementById('orgs-next').disabled = !data.pagination.has_next;
  document.getElementById('orgs-page-info').textContent =
    `Page ${o.page} / ${o.pages} (${o.total} organisation${o.total > 1 ? 's' : ''})`;
  document.querySelector('#panel-organizations .pagination-bar').hidden = !o.total;
}

// Expériences proches : chargées avec la liste des organisations, indépendantes de ses filtres.
async function loadSharedExperiences() {
  const seq = ++_expSeq;
  let data;
  try {
    data = await apiJson('/api/v1/organizations/shared-experiences');
  } catch (err) {
    if (seq === _expSeq) {
      document.getElementById('exp-list').innerHTML =
        '<p class="alert-pgw error">Impossible de charger les expériences proches.</p>';
    }
    throw err;
  }
  if (seq !== _expSeq) return;
  state.experiences.loaded = true;
  state.experiences.undated = data.undated_total || 0;
  state.expCount = data.total;
  if (data.civil_status_total != null) state.civilTotal = data.civil_status_total;
  renderSharedExperiences(data);
  renderExcludedInfo();
}

function experienceTitle(exp) {
  const places = (exp.places || []).map(formatGwName).filter(Boolean);
  const years = exp.year_max != null && exp.year_max !== exp.year_min
    ? `${exp.year_min}-${exp.year_max}` : String(exp.year_min);
  return [formatGwName(exp.label), places.length ? places.join(', ') : 'lieu inconnu', years].join(' · ');
}

function renderSharedExperiences(data) {
  const list = document.getElementById('exp-list');
  document.getElementById('exp-count').textContent = fmtInt(data.total);
  if (!data.items.length) {
    list.innerHTML = '<p class="text-muted exp-empty">Aucune expérience proche trouvée.</p>';
    return;
  }
  const notice = data.truncated
    ? `<p class="text-muted exp-truncated">Liste limitée aux 500 premières expériences sur ${fmtInt(data.total)}.</p>` : '';
  list.innerHTML = notice + data.items.map(exp => {
    const reasons = (exp.reasons || []).map(r => r.kind === 'rare_word'
      ? `Mot commun : ${(r.words || []).join(', ')}` : 'Même lieu');
    const badges = [...new Set(reasons)]
      .map(r => `<span class="badge-pgw">${escHtml(r)}</span>`).join('');
    const rows = (exp.persons || []).map(p => {
      const bits = [p.label, p.year_end != null && p.year_end !== p.year_start
        ? `${p.year_start}-${p.year_end}` : p.year_start, formatGwName(p.place)]
        .filter(b => b !== null && b !== undefined && b !== '');
      return `<li><a href="${escHtml(personHash(p.person_id))}">${escHtml(formatGwName(p.person_name) || p.person_id)}</a>`
        + ` <span class="item-meta">${escHtml(bits.join(' · '))}</span></li>`;
    }).join('');
    return `<details class="item-row org-card exp-card">
      <summary><strong>${escHtml(experienceTitle(exp))}</strong>
        <span class="item-meta org-meta">${fmtInt(exp.person_count)} personne${exp.person_count > 1 ? 's' : ''}</span>
        <span class="org-badges">${badges}</span></summary>
      <ul class="org-members">${rows}</ul>
    </details>`;
  }).join('');
}

// Phrase du panneau replié : actes d'état civil écartés d'office, événements sans date.
function renderExcludedInfo() {
  const civil = state.civilTotal || 0;
  const undated = state.experiences.undated || 0;
  const bits = [];
  if (civil) bits.push(`${fmtInt(civil)} acte${civil > 1 ? 's' : ''} d'état civil écarté${civil > 1 ? 's' : ''} d'office`);
  if (undated) bits.push(`${fmtInt(undated)} événement${undated > 1 ? 's' : ''} sans date`);
  document.getElementById('orgs-excluded-info').textContent = bits.join(' · ');
}

function orgPeriod(org) {
  if (org.first_year == null) return '';
  return org.last_year != null && org.last_year !== org.first_year
    ? `${org.first_year}–${org.last_year}` : String(org.first_year);
}

// Pastilles d'état et de provenance d'un candidat (texte toujours lisible, pas de couleur seule).
function orgBadges(org) {
  const b = [];
  if (org.collective) b.push('<span class="badge-pgw badge-collective">collectif</span>');
  if (org.needs_review) b.push('<span class="badge-pgw badge-review">à revoir</span>');
  if (org.to_determine) b.push('<span class="badge-pgw badge-review">à déterminer</span>');
  if (org.relation) b.push('<span class="badge-pgw badge-circle">cercle</span>');
  if (org.trigger) b.push(`<span class="badge-pgw">${escHtml(org.trigger)}</span>`);
  if (org.named_from) {
    b.push(`<span class="badge-pgw" title="Origine du nom proposé">Nom : ${escHtml(NAMED_FROM_LABELS[org.named_from] || org.named_from)}</span>`);
  }
  const sources = (org.sources || []).map(c => SOURCE_LABELS[c] || c);
  if (sources.length) {
    b.push(`<span class="badge-pgw" title="Types d'événements à l'origine de la proposition">Source : ${escHtml(sources.join(', '))}</span>`);
  }
  return b.join('');
}

function orgCounts(org) {
  return `${fmtInt(org.person_count)} personne${org.person_count > 1 ? 's' : ''} · `
    + `${fmtInt(org.event_count)} événement${org.event_count > 1 ? 's' : ''}`;
}

function renderOrganizations() {
  const list = document.getElementById('orgs-list');
  const unmatched = document.getElementById('orgs-unmatched');
  if (!state.organizations.items.length) {
    list.innerHTML = '<p class="text-muted list-empty">Aucune organisation candidate.</p>';
    unmatched.open = true;
    return;
  }
  list.innerHTML = state.organizations.items.map(org => {
    const meta = [ORG_TYPE_LABELS[org.type] || org.type, formatGwName(org.place), orgCounts(org), orgPeriod(org)]
      .filter(Boolean).join(' · ');
    return `<div class="item-row org-card">
      <span><span class="item-name"><strong>${escHtml(formatGwName(org.name))}</strong></span>
        <span class="item-meta org-meta">${escHtml(meta)}</span>
        <span class="org-badges">${orgBadges(org)}</span></span>
      <button class="btn-see" data-id="${escHtml(org.id)}">Voir ›</button>
    </div>`;
  }).join('');
  list.querySelectorAll('.btn-see').forEach(btn => {
    btn.addEventListener('click', () => navigate(
      drawerShows('organization', btn.dataset.id)
        ? organizationsListHash()
        : organizationHash(btn.dataset.id)));
  });
  markActiveRows();
}

async function openOrganizationDetail(id) {
  if (drawerShows('organization', id)) return;
  const seq = ++_detailSeq;
  setDrawerLoading(true);
  let org;
  try {
    org = await apiJson('/api/v1/organizations/candidates/' + encodeURIComponent(id));
  } catch (err) {
    if (err.message === 'session-expired' || seq !== _detailSeq) return;
    showInDrawer(drawerError('Impossible de charger l\'organisation.'), 'organization', id, null);
    return;
  }
  if (seq !== _detailSeq) return;
  const name = formatGwName(org.name);
  showInDrawer(buildOrganizationPanel(org), 'organization', id, {
    hash: organizationHash(id),
    label: name,
    title: 'Organisation ' + name,
  });
}

function buildOrganizationPanel(org) {
  const meta = [ORG_TYPE_LABELS[org.type] || org.type, formatGwName(org.place), orgCounts(org), orgPeriod(org)]
    .filter(Boolean).join(' · ');
  // Porteur de l'événement ou témoin : précisé dès qu'un membre est témoin.
  const hasWitnesses = (org.members || []).some(m => m.witness);
  const members = (org.members || []).map(m => {
    const label = formatGwName(m.event_label);
    const role = formatGwName(m.role);
    const status = !hasWitnesses ? '' : m.witness ? (role === 'Témoin' ? '' : 'témoin') : 'porteur';
    // Pour une profession, l'événement porte le même texte que le rôle.
    const bits = [status, role, label === role ? '' : label,
      shortDate(m.date), formatGwName(m.place)].filter(Boolean);
    if (!m.witness && m.witness_count > 0) bits.push(`${m.witness_count} témoin${m.witness_count > 1 ? 's' : ''}`);
    return `<li><a href="${escHtml(personHash(m.person_id))}">${escHtml(formatGwName(m.person_name) || m.person_id)}</a>`
      + (bits.length ? ` <span class="item-meta">${escHtml(bits.join(' · '))}</span>` : '') + '</li>';
  }).join('');
  const places = (org.places || []).map(formatGwName).filter(Boolean);
  const why = [];
  if (org.named_from) why.push(`Nom issu de : ${NAMED_FROM_LABELS[org.named_from] || org.named_from}`);
  if (org.trigger) why.push(`Mot déclencheur : ${org.trigger}`);
  if (org.confidence != null) why.push(`Confiance : ${Math.round(org.confidence * 100)} %`);
  const sources = (org.sources || []).map(c => SOURCE_LABELS[c] || c);
  if (sources.length) why.push(`Événements sources : ${sources.join(', ')}`);

  const panel = document.createElement('div');
  panel.className = 'person-detail org-detail';
  panel.dataset.organizationId = org.id;
  panel.innerHTML = `
    <h2 class="drawer-title" tabindex="-1">${escHtml(formatGwName(org.name))}</h2>
    <p class="item-meta">${escHtml(meta)}</p>
    <p class="org-badges">${orgBadges(org)}</p>
    <div class="drawer-section">
      <div class="mini-tree-label">Membres (${(org.members || []).length})</div>
      <ul class="org-members">${members || '<li class="text-muted">Aucun membre.</li>'}</ul>
    </div>
    ${places.length ? `<div class="drawer-section"><div class="mini-tree-label">Lieux</div><p>${escHtml(places.join(' · '))}</p></div>` : ''}
    <details class="drawer-details org-why"><summary>Pourquoi cette proposition ?</summary>
      <ul>${why.map(w => `<li>${escHtml(w)}</li>`).join('')}</ul>
    </details>`;
  return panel;
}

// Mots ignorés : réglage de session côté serveur, retenu dans le navigateur pour les
// fichiers suivants. La première visite (rien de retenu) garde le réglage du serveur.
const IGNORED_WORDS_KEY = 'pgwOrgIgnoredWords';

function savedIgnoredWords() {
  try {
    const saved = JSON.parse(localStorage.getItem(IGNORED_WORDS_KEY));
    return Array.isArray(saved) && saved.every(w => typeof w === 'string') ? saved : null;
  } catch { return null; }
}

function saveIgnoredWords(words) {
  try { localStorage.setItem(IGNORED_WORDS_KEY, JSON.stringify(words)); } catch { /* stockage indisponible */ }
}

// Une seule synchronisation par session, partagée par les appels concurrents.
function syncIgnoredWords() {
  if (state.ignoredWords !== null) return Promise.resolve();
  if (!_ignoredSync) {
    const token = state.token;
    const saved = savedIgnoredWords();
    const request = saved
      ? apiJson('/api/v1/organizations/ignored-words', {
          method: 'PUT', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ words: saved }),
        })
      : apiJson('/api/v1/organizations/ignored-words');
    _ignoredSync = request.then(data => {
      if (state.token !== token) return;
      state.ignoredWords = data.words;
      renderIgnoredWords();
    }).catch(() => { _ignoredSync = null; });   // les candidats restent lisibles sans ce réglage
  }
  return _ignoredSync;
}

async function setIgnoredWords(words) {
  const info = document.getElementById('orgs-ignored-info');
  let data;
  try {
    data = await apiJson('/api/v1/organizations/ignored-words', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ words }),
    });
  } catch (err) {
    if (err.message === 'session-expired') return false;
    info.textContent = err.status === 422
      ? 'Mot refusé : des lettres uniquement, 40 au plus, 50 mots au maximum.'
      : 'Impossible d\'enregistrer les mots ignorés.';
    return false;
  }
  state.ignoredWords = data.words;
  saveIgnoredWords(data.words);
  renderIgnoredWords();
  // Candidats, reste à classer et carte Stats sont recalculés avec le nouveau réglage.
  state.organizations.loaded = false;
  state.experiences.loaded = false;
  state.expCount = null;
  state.unmatchedLoaded = false;
  state.orgCount = null;
  navigate(organizationsListHash(1));
  return true;
}

function renderIgnoredWords() {
  const chips = document.getElementById('orgs-ignored-chips');
  const words = state.ignoredWords || [];
  chips.innerHTML = words.length
    ? words.map(w => `<span class="badge-pgw ignored-chip">${escHtml(w)}`
        + `<button type="button" data-word="${escHtml(w)}" aria-label="Ne plus ignorer « ${escHtml(w)} »">×</button></span>`).join('')
    : '<span class="text-muted">aucun</span>';
  chips.querySelectorAll('button[data-word]').forEach(btn => {
    btn.addEventListener('click', () => setIgnoredWords(words.filter(w => w !== btn.dataset.word)));
  });
}

// Reste à classer : événements « Autre » sans candidat, groupés par mot.
async function loadUnmatched() {
  if (state.unmatchedLoaded) return;
  state.unmatchedLoaded = true;
  const body = document.getElementById('orgs-unmatched-body');
  try {
    renderUnmatched(await apiJson('/api/v1/organizations/unmatched'));
  } catch (err) {
    state.unmatchedLoaded = false;
    if (err.message === 'session-expired') return;
    body.innerHTML = '<p class="alert-pgw error">Impossible de charger le reste à classer.</p>';
  }
}

function renderUnmatched(data) {
  const summary = document.getElementById('orgs-unmatched-summary');
  const body = document.getElementById('orgs-unmatched-body');
  summary.textContent = `Reste à classer (${fmtInt(data.total)} événement${data.total > 1 ? 's' : ''})`;
  state.civilTotal = data.civil_status_total || 0;
  renderExcludedInfo();
  const ignored = data.ignored_total || 0;
  document.getElementById('orgs-ignored-info').textContent = ignored
    ? `${fmtInt(ignored)} événement${ignored > 1 ? 's' : ''} écarté${ignored > 1 ? 's' : ''}` : '';
  if (!data.groups.length) {
    body.innerHTML = '<p class="text-muted unmatched-empty">Aucun événement à classer.</p>';
    return;
  }
  body.innerHTML = data.groups.map(g => {
    const events = g.events.map(e => {
      const bits = [e.label, shortDate(e.date), formatGwName(e.place)].filter(Boolean);
      return `<li><a href="${escHtml(personHash(e.person_id))}">${escHtml(formatGwName(e.person_name) || e.person_id)}</a>`
        + ` <span class="item-meta">${escHtml(bits.join(' · '))}</span></li>`;
    }).join('');
    const ignoreBtn = g.word === 'autres' ? ''
      : `<button type="button" class="unmatched-ignore" data-word="${escHtml(g.word)}">Ignorer ce mot</button>`;
    return `<details class="unmatched-group"><summary>${escHtml(g.word)} · ${fmtInt(g.count)}${ignoreBtn}</summary>`
      + `<ul class="org-members">${events}</ul></details>`;
  }).join('');
  body.querySelectorAll('.unmatched-ignore').forEach(btn => {
    btn.addEventListener('click', e => {
      e.preventDefault();   // ne pas replier le groupe
      setIgnoredWords([...(state.ignoredWords || []), btn.dataset.word]);
    });
  });
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
  renderOrganizationsStat();
}

// Cartes « Organisations candidates » et « Expériences proches » : effectifs, liens vers l'onglet.
async function renderOrganizationsStat() {
  const grid = document.querySelector('#stats-content .stats-grid');
  if (!grid) return;
  if (state.orgCount === null || state.expCount === null) {
    await syncIgnoredWords();
    try {
      if (state.orgCount === null) {
        const data = await apiJson('/api/v1/organizations/candidates?size=1');
        state.orgCount = data.pagination.total;
      }
      if (state.expCount === null) {
        const data = await apiJson('/api/v1/organizations/shared-experiences');
        state.expCount = data.total;
      }
    } catch { /* complément : la page Stats reste complète sans lui */ }
  }
  if (!grid.isConnected) return;
  for (const [key, count, label, href] of [
    ['orgs', state.orgCount, 'Organisations candidates', '#/organisations'],
    ['exps', state.expCount, 'Expériences proches', '#/organisations?section=experiences'],
  ]) {
    if (count === null || grid.querySelector(`[data-stat="${key}"]`)) continue;
    grid.insertAdjacentHTML('beforeend',
      `<a class="stat-card stat-card-link" data-stat="${key}" href="${href}">
        <div class="stat-value">${escHtml(String(count))}</div>
        <div class="stat-label">${label}</div>
      </a>`);
  }
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
const EXPORT_FILENAMES = {
  gedcom: 'genealogie.ged', json: 'genealogie.json', xml: 'genealogie.xml',
  'org-json': 'genealogie.org.json',
  'organizations-csv': 'organisations.csv',
  'organization-links-csv': 'liens_organisations.csv',
  'shared-experiences-csv': 'experiences_proches.csv',
};

async function downloadExport(format) {
  const errorEl = document.getElementById('export-error');
  errorEl.style.display = 'none';
  try {
    if (format.startsWith('org') || format.startsWith('shared')) await syncIgnoredWords();
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
    a.download = EXPORT_FILENAMES[format];
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
  document.getElementById('btn-export-org-json').addEventListener('click', () => downloadExport('org-json'));
  document.getElementById('btn-export-org-csv').addEventListener('click', () => downloadExport('organizations-csv'));
  document.getElementById('btn-export-org-links-csv').addEventListener('click', () => downloadExport('organization-links-csv'));
  document.getElementById('btn-export-exp-csv').addEventListener('click', () => downloadExport('shared-experiences-csv'));
}
