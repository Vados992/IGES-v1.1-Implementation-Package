'use strict';
const root = document.getElementById('publication');
function add(tag, text, parent = root, className = '') { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; parent.append(node); return node; }
async function show() {
  const id = location.hash.slice(1); if (!/^[a-f0-9-]{36}$/i.test(id)) throw new Error('Publication identifier required / Нужен идентификатор публикации');
  const response = await fetch(`/v1/public/publications/${id}/manifest`); if (!response.ok) throw new Error('Publication unavailable / Публикация недоступна');
  const raw = await response.arrayBuffer(), sha = [...new Uint8Array(await crypto.subtle.digest('SHA-256', raw))].map(x => x.toString(16).padStart(2,'0')).join('');
  if (sha !== response.headers.get('X-Manifest-SHA256')) throw new Error('Integrity check failed / Проверка целостности не пройдена');
  const manifest = JSON.parse(new TextDecoder().decode(raw)); root.replaceChildren(); add('h1', manifest.case.title);
  add('span', `${manifest.kind} · Version / Версия ${manifest.version} · Revision / Редакция ${manifest.revision}`, root, 'badge');
  add('p', manifest.case.scope); add('p', manifest.reason); add('code', `SHA-256: ${sha}`);
  const history = await (await fetch(`/v1/public/cases/${manifest.case_id}/publications`)).json();
  if (history.records.some(r => r.supersedes_id === id)) add('p', 'This historical version is superseded. / Эта историческая версия заменена.', root, 'badge warning');
  const links = add('div', '', root, 'actions');
  for (const record of history.records) { const link = add('a', `${record.version} · ${record.kind}`, links); link.href = '/publication#' + record.id; }
  add('h2', 'Claims and findings / Утверждения и выводы');
  for (const claim of manifest.claims) { const card = add('section', '', root, 'record'); add('h3', claim.exact_text, card); add('span', claim.status, card, 'badge'); add('p', `${claim.period_from} — ${claim.period_to} · ${claim.jurisdictions.join(', ')}`, card); add('p', claim.scope_note, card); for (const review of claim.reviews) { add('p', review.assessment.rationale, card); add('p', review.assessment.limitations, card); } }
  add('h2', 'Source quotations / Цитаты источников');
  for (const evidence of manifest.records.evidence_items) { const card = add('section', '', root, 'record'); add('blockquote', evidence.body.quote, card); add('p', `Page / Страница ${evidence.body.page} · ${evidence.body.direction}`, card); add('p', evidence.body.limitations.join('; '), card); if (evidence.body.translation) add('p', 'Translation / Перевод: ' + evidence.body.translation, card); }
  add('h2', 'Sources / Источники');
  for (const source of manifest.records.sources) { const item = add('p', `${source.body.publisher} · ${source.body.primacy} · `); const link = add('a', source.body.title, item); if (source.body.url.startsWith('https://')) link.href = source.body.url; link.rel = 'noopener noreferrer'; link.target = '_blank'; }
  add('h2', 'Responses / Ответы сторон'); for (const reply of manifest.responses) add('blockquote', reply.body.text);
  add('p', manifest.reply_disposition.rationale); add('h2', 'Methodology / Методология'); add('p', manifest.methodology_version); add('p', manifest.methodology);
  const download = add('a', 'Immutable manifest / Неизменяемый манифест'); download.href = `/v1/public/publications/${id}/manifest`;
}
window.addEventListener('hashchange', () => show().catch(error => {root.textContent = error.message;}));
show().catch(error => {root.textContent = error.message;});
