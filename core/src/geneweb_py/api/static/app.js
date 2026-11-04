'use strict';

// ==================== STATE ====================
const state = {
  token: sessionStorage.getItem('gwToken') || null,
  expiresAt: sessionStorage.getItem('gwExpiresAt') || null,
  stats: null,
  persons: { items: [], page: 1, pages: 1 },
  families: { items: [], page: 1, pages: 1, nameMap: {} },
  currentPersonId: null,
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
  state.expiresAt = null;
  sessionStorage.removeItem('gwToken');
  sessionStorage.removeItem('gwExpiresAt');
  if (_timerInterval) { clearInterval(_timerInterval); _timerInterval = null; }
  showLanding();
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
  await loadPersons(1, '');
}

async function init() {
  wireUploadZone();
  wireQuit();
  wireTabs();
  wirePersonsTab();
  wireFamiliesTab();
  initEventsTab();
  wireExportTab();

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
    tab.addEventListener('click', () => showTab(tab.dataset.tab));
  });
}

function showTab(name) {
  document.querySelectorAll('.pgw-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === `panel-${name}`));
  if (name === 'families' && state.families.items.length === 0) loadFamilies(1);
  if (name === 'stats') renderStats();
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

  searchBtn.addEventListener('click', () => {
    loadPersons(1, searchInput.value.trim());
  });

  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadPersons(1, searchInput.value.trim());
  });

  clearBtn.addEventListener('click', () => {
    searchInput.value = '';
    loadPersons(1, '');
  });

  prevBtn.addEventListener('click', () => {
    const query = searchInput.value.trim();
    loadPersons(state.persons.page - 1, query);
  });

  nextBtn.addEventListener('click', () => {
    const query = searchInput.value.trim();
    loadPersons(state.persons.page + 1, query);
  });
}

async function loadPersons(page, query) {
  const seq = ++_personsSeq;
  let url = `/api/v1/persons/?page=${page}&size=50`;
  if (query) url += `&query=${encodeURIComponent(query)}`;
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
  state.persons.items = data.items;
  state.persons.page = data.pagination.page;
  state.persons.pages = data.pagination.pages;
  state.currentPersonId = null;
  renderPersons();
  updatePersonPagination(data.pagination);
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
    btn.addEventListener('click', () => showPersonDetail(btn.dataset.id, btn));
  });
}

function updatePersonPagination(pagination) {
  document.getElementById('persons-prev').disabled = !pagination.has_prev;
  document.getElementById('persons-next').disabled = !pagination.has_next;
  document.getElementById('persons-page-info').textContent =
    `Page ${pagination.page} / ${pagination.pages} (${pagination.total} personnes)`;
  // Pas de pagination « Page 1 / 0 » quand il n'y a aucun résultat.
  document.querySelector('#panel-persons .pagination-bar').hidden = !pagination.total;
}

// ==================== FICHE PERSONNE ====================
async function showPersonDetail(personId, btnEl) {
  const existing = document.getElementById('person-detail-panel');
  if (existing) {
    const wasForSamePerson = existing.dataset.personId === personId;
    existing.remove();
    if (wasForSamePerson) return;
  }

  state.currentPersonId = personId;

  let personResp, familiesResp;
  try {
    [personResp, familiesResp] = await Promise.all([
      apiJson('/api/v1/persons/' + encodeURIComponent(personId)),
      apiJson('/api/v1/persons/' + encodeURIComponent(personId) + '/families'),
    ]);
  } catch (err) {
    if (err.message === 'session-expired') return; // handled by apiFetch
    const row = btnEl ? btnEl.closest('.item-row') : null;
    const errPanel = document.createElement('div');
    errPanel.className = 'alert-pgw error';
    errPanel.textContent = 'Impossible de charger la fiche.';
    if (row) row.insertAdjacentElement('afterend', errPanel);
    else document.getElementById('persons-list').prepend(errPanel);
    return;
  }

  const person = personResp.data;
  const families = familiesResp.data || [];

  const spouseFamilyIds = new Set(person.related_families || []);

  const parentIds = [];
  const childIds = [];
  const partnerIds = [];

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

  const parents = uniqueParentIds.map(id => ({ id, label: nameMap[id] || id }));
  const children = uniqueChildIds.map(id => ({ id, label: nameMap[id] || id }));
  const partners = uniquePartnerIds.map(id => ({ id, label: nameMap[id] || id }));

  const panel = buildPersonDetailPanel(person, parents, partners, children);
  panel.dataset.personId = personId;

  const row = btnEl ? btnEl.closest('.item-row') : null;
  if (row) {
    row.insertAdjacentElement('afterend', panel);
  } else {
    document.getElementById('persons-list').prepend(panel);
  }

  panel.querySelectorAll('.mini-tree-person[data-id]').forEach(el => {
    el.addEventListener('click', () => showPersonDetail(el.dataset.id, null));
  });
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
      `<a class="mini-tree-person" data-id="${escHtml(id)}">${escHtml(label)}</a>`
    ).join('');
  }

  const partnersHtml = partners.length
    ? `<div class="mini-tree-label" style="margin-top:0.4rem">⚭ Partenaire(s)</div>${renderPersonNodes(partners)}`
    : '';

  panel.innerHTML = `
    <div>
      <strong>${fullName}</strong>${datesHtml}
    </div>
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
    loadFamilies(state.families.page - 1);
  });
  document.getElementById('families-next').addEventListener('click', () => {
    loadFamilies(state.families.page + 1);
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
    btn.addEventListener('click', () => showFamilyDetail(btn.dataset.id, btn));
  });
}

function updateFamiliesPagination(pagination) {
  document.getElementById('families-prev').disabled = !pagination.has_prev;
  document.getElementById('families-next').disabled = !pagination.has_next;
  document.getElementById('families-page-info').textContent =
    `Page ${pagination.page} / ${pagination.pages} (${pagination.total} familles)`;
  document.querySelector('#panel-families .pagination-bar').hidden = !pagination.total;
}

async function showFamilyDetail(familyId, btnEl) {
  const existing = document.getElementById('family-detail-panel');
  if (existing) {
    const wasForSameFamily = existing.dataset.familyId === familyId;
    existing.remove();
    if (wasForSameFamily) return;
  }

  const row = btnEl ? btnEl.closest('.item-row') : null;

  let childrenResp;
  try {
    childrenResp = await apiJson('/api/v1/families/' + encodeURIComponent(familyId) + '/children');
  } catch (err) {
    if (err.message === 'session-expired') return;
    const errPanel = document.createElement('div');
    errPanel.className = 'alert-pgw error';
    errPanel.textContent = 'Impossible de charger les enfants.';
    if (row) row.insertAdjacentElement('afterend', errPanel);
    else document.getElementById('families-list').prepend(errPanel);
    return;
  }

  const children = childrenResp.data || [];

  const panel = document.createElement('div');
  panel.id = 'family-detail-panel';
  panel.className = 'person-detail';
  panel.dataset.familyId = familyId;

  let childrenHtml;
  if (children.length) {
    childrenHtml = children.map(child => {
      const person = child.person || {};
      const childId = child.person_id || person.id || '';
      const label = person.surname || person.first_name
        ? escHtml(personLabel(person.surname, person.first_name))
        : escHtml(childId || '—');
      return `<a class="mini-tree-person" data-id="${escHtml(childId)}">${label}</a>`;
    }).join('');
  } else {
    childrenHtml = '<em style="color:var(--text-muted);font-size:0.85rem">Aucun enfant enregistré.</em>';
  }

  panel.innerHTML = `
    <div><strong>Enfants :</strong></div>
    <div>${childrenHtml}</div>
  `;

  panel.querySelectorAll('a.mini-tree-person[data-id]').forEach(el => {
    el.addEventListener('click', () => {
      showTab('persons');
      showPersonDetail(el.dataset.id, null);
    });
  });

  if (row) {
    row.insertAdjacentElement('afterend', panel);
  } else {
    document.getElementById('families-list').prepend(panel);
  }
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

  let tableHtml = '';
  const eventsByType = s.events_by_type;
  if (eventsByType && Object.keys(eventsByType).length > 0) {
    const rows = Object.entries(eventsByType).map(([key, count]) => {
      const typeEntry = EVENT_TYPES.find(t => t.value === key);
      const label = typeEntry ? typeEntry.label : escHtml(key);
      return `<tr><td>${label}</td><td>${escHtml(String(count))}</td></tr>`;
    }).join('');
    tableHtml = `
      <h3 style="color:var(--accent);margin-top:1.5rem">Événements par type</h3>
      <div style="max-width:400px">
        <table class="table table-sm">
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  }

  container.innerHTML = gridHtml + tableHtml;
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
