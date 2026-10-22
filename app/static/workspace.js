'use strict';
let token = '', locale = 'en', strings = {}, specification = {}, current = null, activeTab = 'claims';
const $ = id => document.getElementById(id);
const t = key => strings[locale]?.[key] || strings.en?.[key] || key;
const fieldName = key => strings[locale]?.fields[key] || strings.en?.fields[key] || key.replaceAll('_', ' ');
const tabs = ['claims', 'documents', 'evidence', 'graph', 'review', 'legal', 'publication'];
const actions = {
  claims: [['createClaim', 'Claim', 'claims'], ['createHypothesis', 'Hypothesis', 'hypotheses'], ['withdraw','Withdrawal','claim-withdrawal'], ['amendCase','CaseRevision','case-revisions']],
  documents: [['createSource', 'Source', 'sources'], ['upload', null, 'documents']],
  evidence: [['createEvidence', 'EvidenceItem', 'evidence-items']],
  graph: [['createEntity', 'Entity', 'entities'], ['createRelationship', 'Relationship', 'relationships'], ['resolveEntity','EntityResolution','entity-resolutions']],
  review: [['assign', 'Assignment', 'review-assignments'], ['assess', 'Assessment', 'assessments'], ['member', 'Member', 'members'], ['revokeMember','MemberRevocation','member-revocations']],
  legal: [['legalGate', 'LegalGate', 'legal-privacy'], ['replyGate', 'ReplyGate', 'reply-window'],
          ['panelGate', 'PanelGate', 'panel'], ['partyResponse', 'Response', 'responses']],
  publication: [['publish', 'Publication', 'publications']]
};
const tableTabs = {claims: ['claims','hypotheses'], documents:['sources','documents'], evidence:['evidence_items'],
  graph:['entities','relationships','entity_resolutions'], review:['review_assignments','assessments'], legal:['publication_gates','responses'], publication:['publications']};

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) node.textContent = value;
  if (className) node.className = className;
  return node;
}
function message(value) { $('message').textContent = value; }
function button(label, action, secondary = true) {
  const node = element('button', label, secondary ? 'secondary' : ''); node.type = 'button';
  node.addEventListener('click', () => Promise.resolve().then(action).catch(showError)); return node;
}
function showError(error) { message(error.message || t('error')); }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, credentials: 'omit', headers: {Authorization: 'Bearer ' + token, ...options.headers}});
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    if (response.status === 401) disconnect();
    throw new Error((t(problem.detail || 'error')) + ' · ' + response.status + ' · ' + (response.headers.get('X-Request-ID') || ''));
  }
  return response;
}
async function json(path, options) { return (await api(path, options)).json(); }
function translate() {
  document.documentElement.lang = locale;
  document.querySelectorAll('[data-t]').forEach(node => node.textContent = t(node.dataset.t));
  if (token) { loadCases().catch(showError); if (current) renderCase(); }
}
function disconnect() {
  token = ''; current = null; $('accessToken').value = ''; $('session').hidden = true;
  $('connection').hidden = false; $('identity').textContent = ''; $('caseList').replaceChildren();
  $('records').replaceChildren(); $('editor').replaceChildren(); message(t('noSession'));
}
async function loadCases() {
  const data = await json('/v1/cases'); $('caseList').replaceChildren();
  if (!data.records.length) $('caseList').append(element('p', t('empty'), 'empty'));
  for (const record of data.records) {
    const node = button(record.body.title, () => openCase(record.id)); node.className = 'case-button';
    if (current?.id === record.id) node.classList.add('active'); $('caseList').append(node);
  }
}
async function openCase(id) { current = await json('/v1/cases/' + id); renderCase(); await loadCases(); }
function renderCase() {
  const header = $('caseHeader'); header.replaceChildren(element('h1', current.body.title), element('p', current.body.scope));
  const meta = element('div', `${current.body.period_from} — ${current.body.period_to} · ${current.body.jurisdictions.join(', ')} · ${t('revision')} ${current.case_revision}`, 'muted');
  header.append(meta, button(t('refresh'), () => openCase(current.id)));
  const search = element('form'); const input = element('input'); input.placeholder = t('query'); input.required = true;
  const submit = element('button', t('search')); search.append(input, submit);
  search.addEventListener('submit', async event => {
    event.preventDefault(); try {
      const result = await json(`/v1/cases/${current.id}/search?q=${encodeURIComponent(input.value)}`);
      $('records').replaceChildren();
      for (const record of result.records) {
        const node = element('article', undefined, 'record'); node.append(element('span', record.kind, 'badge'), element('span', `${fieldName('page')}: ${record.page ?? '—'}`));
        node.append(element('blockquote', record.fragment)); $('records').append(node);
      }
      if (!result.records.length) $('records').append(element('p', t('empty'), 'empty'));
    } catch (error) { showError(error); }
  }); header.append(search);
  $('tabs').replaceChildren();
  for (const tab of tabs) { const node = button(t(tab), () => { activeTab = tab; renderCase(); }); if (tab === activeTab) node.classList.add('active'); $('tabs').append(node); }
  renderRecords(); $('editor').replaceChildren();
  const choices = actions[activeTab]; const select = element('select'); select.setAttribute('aria-label', t(activeTab));
  for (const [label] of choices) { const option = element('option', t(label)); option.value = label; select.append(option); }
  const holder = element('section');
  const change = () => { holder.replaceChildren(); buildForm(choices.find(action => action[0] === select.value), holder); };
  select.addEventListener('change', change); $('editor').append(select, holder); change();
}
function renderRecords() {
  const root = $('records'); root.replaceChildren(); let count = 0;
  for (const table of tableTabs[activeTab]) {
    for (const record of current.records[table] || []) {
      count++; const body = record.body || {}, node = element('article', undefined, 'record');
      const title = body.title || body.exact_text || body.statement || body.canonical_name || body.predicate || record.status || record.kind || t(activeTab);
      node.append(element('h3', title));
      if (table === 'claims') {
        const decisions = (current.records.assessments || []).filter(a => a.claim_id === record.id && (a.revision === current.case_revision || a.status === 'WITHDRAWN_CORRECTED'));
        node.append(element('span', decisions.length ? [...new Set(decisions.map(a => a.status))].join(' / ') : 'UNASSESSED', 'badge'));
      }
      if (body.quote) node.append(element('blockquote', body.quote));
      for (const key of ['scope_note','falsifiers','expected_observations','limitations','rationale','provenance_basis','identity_basis','text']) {
        if (body[key]) node.append(element('p', `${fieldName(key)}: ${Array.isArray(body[key]) ? body[key].join('; ') : body[key]}`));
      }
      if (body.url) { const link = element('a', body.publisher || t('source')); if (body.url.startsWith('https://')) link.href = body.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; node.append(link); }
      if (table === 'evidence_items') node.append(element('p', `${fieldName('page')}: ${body.page} · ${body.direction}`));
      if (table === 'documents') {
        node.append(element('span', record.processing_status || 'PENDING', 'badge'), element('p', `${record.size_bytes} bytes · ${record.detected_mime || record.mime}`), element('code', record.sha256));
        const controls = element('div', undefined, 'actions');
        controls.append(button(t('pages'), () => showPages(record.id, node)), button(t('download'), () => download(record.id)),
          button(t('verify'), async () => { const result = await write(`/documents/${record.id}/verify`, {}, undefined, false); message(t(result.integrity_checked ? 'intact' : 'failed')); }));
        if (['FAILED','QUARANTINED'].includes(record.processing_status)) controls.append(button(t('retry'), async () => { await write(`/documents/${record.id}/retry`, {}, undefined, false); await openCase(current.id); }));
        node.append(controls);
      }
      if (table === 'publications') {
        node.append(element('p', `${t('revision')} ${record.revision} · ${t('history')} ${record.version}`));
        const links = element('div', undefined, 'actions');
        for (const [label, href] of [['manifest', `/v1/public/publications/${record.id}/manifest`], ['reader', `/publication#${record.id}`], ['csv', `/v1/public/publications/${record.id}/claims.csv`]]) {
          const link = element('a', t(label)); link.href = href; link.target = '_blank'; link.rel = 'noopener'; links.append(link);
        } node.append(links);
      }
      node.append(element('code', record.id)); root.append(node);
    }
  }
  if (!count) root.append(element('p', t('empty'), 'empty'));
}
async function showPages(id, node) {
  const result = await json(`/v1/cases/${current.id}/documents/${id}/pages`);
  node.querySelectorAll('.page-display').forEach(old => old.remove());
  const display = element('section', undefined, 'page-display');
  for (const page of result.pages) {
    display.append(element('h3', `${fieldName('page')} ${page.page}`));
    if (page.confidence !== null) display.append(element('span', `${t('confidence')}: ${(Number(page.confidence)*100).toFixed(1)}%`, 'badge'));
    if (page.confidence !== null && Number(page.confidence) < .85) display.append(element('span', t('manual'), 'badge warning'));
    display.append(element('pre', page.text_content, 'page-text'));
  }
  if (!result.pages.length) display.append(element('p', result.processing[0]?.status || 'PENDING'));
  node.append(display);
}
async function download(id) {
  const response = await api(`/v1/cases/${current.id}/documents/${id}/original`), url = URL.createObjectURL(await response.blob());
  const anchor = element('a'); anchor.href = url; anchor.download = id + '.original'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function write(suffix, body, key, isNewCase = false, binary = false) {
  const headers = {'Idempotency-Key': key || crypto.randomUUID()};
  if (!isNewCase) headers['If-Match'] = `"${current.case_revision}"`;
  headers['Content-Type'] = binary ? 'application/octet-stream' : 'application/json';
  return json(isNewCase ? '/v1/cases' : '/v1/cases/' + current.id + suffix, {method:'POST', headers, body: binary ? body : JSON.stringify(body)});
}
function base64url(bytes) { return btoa(String.fromCharCode(...bytes)).replaceAll('+','-').replaceAll('/','_').replace(/=+$/,''); }
async function oidcMetadata() {
  const response = await fetch('/v1/auth/config', {credentials:'omit'});
  if (!response.ok) throw new Error(t('OIDC_NOT_CONFIGURED'));
  const config = await response.json(), issuer = new URL(config.issuer);
  if (issuer.protocol !== 'https:') throw new Error(t('OIDC_NOT_CONFIGURED'));
  const discovery = await fetch(config.issuer.replace(/\/$/,'') + '/.well-known/openid-configuration', {credentials:'omit'});
  if (!discovery.ok) throw new Error(t('OIDC_NOT_CONFIGURED'));
  const metadata = await discovery.json();
  if (metadata.issuer !== config.issuer || ['authorization_endpoint','token_endpoint'].some(key => new URL(metadata[key]).origin !== issuer.origin)) throw new Error(t('OIDC_NOT_CONFIGURED'));
  return {config, metadata};
}
async function connectIdentity(accessToken) {
  token = accessToken;
  const user = await json('/v1/admin/whoami'); $('identity').textContent = user.subject + ' · ' + user.roles.join(', ');
  $('connection').hidden = true; $('session').hidden = false; message(''); await loadCases();
}
async function beginSSO() {
  const {config, metadata} = await oidcMetadata();
  const verifier = base64url(crypto.getRandomValues(new Uint8Array(48))), state = base64url(crypto.getRandomValues(new Uint8Array(32)));
  const challenge = base64url(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))));
  const redirectUri = location.origin + '/workspace';
  sessionStorage.setItem('iges-pkce', JSON.stringify({verifier,state,redirectUri,createdAt:Date.now()}));
  const url = new URL(metadata.authorization_endpoint);
  url.search = new URLSearchParams({client_id:config.client_id,response_type:'code',scope:'openid',redirect_uri:redirectUri,
    state,code_challenge:challenge,code_challenge_method:'S256',max_age:'0',prompt:'login'}).toString();
  location.assign(url.href);
}
async function completeSSO() {
  const query = new URLSearchParams(location.search);
  if (!query.has('code') && !query.has('error')) return;
  history.replaceState(null, '', location.pathname);
  const saved = JSON.parse(sessionStorage.getItem('iges-pkce') || 'null'); sessionStorage.removeItem('iges-pkce');
  if (!saved || Date.now()-saved.createdAt > 600000 || query.get('state') !== saved.state || !query.get('code')) throw new Error(t('noSession'));
  const {config, metadata} = await oidcMetadata();
  const response = await fetch(metadata.token_endpoint, {method:'POST', credentials:'omit',
    headers:{'Content-Type':'application/x-www-form-urlencoded'}, body:new URLSearchParams({client_id:config.client_id,
      grant_type:'authorization_code',code:query.get('code'),redirect_uri:saved.redirectUri,code_verifier:saved.verifier})});
  if (!response.ok) throw new Error(t('noSession'));
  const result = await response.json(); await connectIdentity(result.access_token);
}
function buildForm(action, holder, isNewCase = false) {
  const [label, model, endpoint] = action; holder.append(element('h2', t(label)));
  const form = element('form'), controls = [];
  if (model === 'LegalGate' || model === 'Assessment' || model === 'Publication') form.append(element('p', t('noApproval'), 'full field-help'));
  const schema = model ? specification.components.schemas[model] : {properties: {source_id:{type:'string',format:'uuid'},file:{type:'file'}}, required:['source_id','file']};
  const fields = model === 'Withdrawal' ? {claim_id:{type:'string',format:'uuid'},...schema.properties} : schema.properties;
  for (const [name, raw] of Object.entries(fields)) {
    const prop = raw.anyOf ? raw.anyOf.find(option => option.type !== 'null') : raw;
    if (prop.const !== undefined && prop.const !== true) continue;
    const required = (model === 'Withdrawal' && name === 'claim_id') || schema.required?.includes(name), wrapper = element('label'); wrapper.append(element('span', name === 'file' ? t('file') : fieldName(name)));
    let input, kind = prop.type;
    const refs = {claim_id:'claims',document_id:'documents',evidence_id:'evidence_items',request_evidence_id:'evidence_items',source_id:'sources',reverses_id:'entity_resolutions',subject_id:'entities',object_id:'entities',supersedes_id:model === 'Claim' ? 'claims' : 'publications'};
    if (refs[name] && current) {
      input = element('select'); const blank = element('option', t('choose')); blank.value = ''; input.append(blank);
      for (const record of current.records[refs[name]] || []) {
        const body = record.body || {}, option = element('option', (body.title || body.exact_text || body.canonical_name || body.quote || record.sha256 || record.kind || record.id).slice(0,100)); option.value = record.id; input.append(option);
      }
    } else if (prop.enum) {
      input = element('select'); const blank = element('option', t('choose')); blank.value = ''; input.append(blank);
      for (const value of prop.enum) { const option = element('option', value); option.value = value; input.append(option); }
    } else if (kind === 'boolean' || prop.const === true) { input = element('input'); input.type = 'checkbox'; kind = 'boolean'; }
    else if (kind === 'file') { input = element('input'); input.type = 'file'; }
    else if (kind === 'array' || kind === 'object' || (prop.maxLength || 0) > 1000) {
      input = element('textarea'); wrapper.classList.add('full');
      if (kind === 'array' || kind === 'object') wrapper.append(element('span', t(kind === 'array' ? 'lineList' : 'pairList'), 'field-help'));
    } else { input = element('input'); input.type = prop.format === 'date' ? 'date' : prop.format === 'date-time' ? 'datetime-local' : kind === 'integer' ? 'number' : 'text'; }
    input.name = name; input.setAttribute('aria-label', name === 'file' ? t('file') : fieldName(name)); input.required = !!required && (kind !== 'boolean' || prop.const === true);
    if (prop.minLength) input.minLength = prop.minLength;
    if (prop.maxLength) input.maxLength = prop.maxLength;
    if (prop.minimum !== undefined) input.min = prop.minimum;
    if (prop.maximum !== undefined) input.max = prop.maximum;
    input.autocomplete = 'off'; wrapper.append(input); form.append(wrapper); controls.push({name,input,kind,required,prop});
  }
  const submit = element('button', t('save')); submit.type = 'submit'; form.append(submit);
  let attempt = null;
  form.addEventListener('input', () => { attempt = null; });
  form.addEventListener('submit', async event => {
    event.preventDefault(); submit.disabled = true;
    try {
      const body = {};
      for (const {name,input,kind,required,prop} of controls) {
        if (kind === 'file') continue;
        if (!input.value && !required && kind !== 'boolean') continue;
        let value = kind === 'boolean' ? input.checked : input.value;
        if (kind === 'array') value = input.value.split('\n').map(item => item.trim()).filter(Boolean);
        if (kind === 'object') value = Object.fromEntries(input.value.split('\n').filter(line => line.trim()).map(line => { const at = line.indexOf(':'); if (at < 1) throw new Error(t('pairList')); return [line.slice(0,at).trim(),line.slice(at+1).trim()]; }));
        if (kind === 'integer') value = Number(value);
        if (prop.format === 'date-time') value = new Date(value + 'Z').toISOString();
        body[name] = value;
      }
      const signature = JSON.stringify(body);
      if (!attempt || attempt.signature !== signature) attempt = {signature, key:crypto.randomUUID()};
      let result;
      if (!model) {
        const file = controls.find(item => item.kind === 'file').input.files[0];
        if (!file || file.size > 8388608) throw new Error(t('file'));
        result = await write('/documents?source_id=' + body.source_id, file, attempt.key, false, true);
      } else if (model === 'Withdrawal') { const claim = body.claim_id; delete body.claim_id; result = await write('/claims/' + claim + '/withdrawal', body, attempt.key); } else result = await write('/' + endpoint, body, attempt.key, isNewCase);
      attempt = null; await openCase(isNewCase ? result.id : current.id); message(t('saved'));
    } catch (error) { showError(error); } finally { submit.disabled = false; }
  }); holder.append(form);
}
async function start() {
  strings = await (await fetch('/assets/workspace-i18n.json')).json(); specification = await (await fetch('/openapi.json')).json(); translate();
  $('language').addEventListener('change', event => { locale = event.target.value; translate(); });
  $('disconnect').addEventListener('click', disconnect);
  $('oidcLogin').addEventListener('click', () => beginSSO().catch(showError));
  $('newCase').addEventListener('click', () => { $('editor').replaceChildren(); buildForm(['newCase','Case','cases'], $('editor'), true); });
  $('connectForm').addEventListener('submit', async event => {
    event.preventDefault(); token = $('accessToken').value.trim(); $('accessToken').value = '';
    try { await connectIdentity(token); } catch (error) { disconnect(); showError(error); }
  });
  await completeSSO();
}
start().catch(showError);
