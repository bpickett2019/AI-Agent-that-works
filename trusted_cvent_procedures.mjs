/**
 * Trusted, bounded Cvent procedures.
 *
 * This module is application code, not a model-programmable browser surface.
 * Callers choose a named procedure and provide validated RR values only. Routes,
 * selectors, sequencing, mutation boundaries, and verification are owned here.
 */

const STATUS = new Set([
  'CONFIGURED', 'ALREADY_CORRECT', 'AUTH_REQUIRED', 'CONTROL_NOT_FOUND',
  'UNEXPECTED_UI', 'AMBIGUOUS', 'VERIFY_FAILED',
]);
const norm = value => String(value ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
const token = () => `cvent-trusted-${Date.now()}-${Math.random().toString(16).slice(2)}`;

export function eventKeyFromUrl(value) {
  try {
    const url = new URL(value);
    // Cvent's admission grid emits evtStub; detail pages also use evtstub.
    // Normalize parameter names, not just values. Reject conflicting aliases.
    const keys = [...url.searchParams].filter(([name]) => ['evtstub', 'eventid', 'event'].includes(name.toLowerCase())).map(([, key]) => norm(key));
    return keys.length && keys.every(key => key && key === keys[0]) ? keys[0] : '';
  } catch { return ''; }
}

async function pageDisposition(ego, eventKey) {
  const page = await ego.pageInfo();
  const url = new URL(page.url);
  const host = url.hostname.toLowerCase();
  const login = /(?:login|signin|authenticate|sso)/i.test(page.url) || host !== 'app.cvent.com' || url.protocol !== 'https:';
  if (login) return { status: 'AUTH_REQUIRED', page };
  if (eventKeyFromUrl(page.url) !== norm(eventKey)) {
    return { status: 'UNEXPECTED_UI', page, detail: 'Exact authorized event key is absent from the current Cvent page' };
  }
  return { status: null, page };
}

async function gotoAuthorized(ego, url, eventKey) {
  const parsed = new URL(url);
  if (parsed.hostname.toLowerCase() !== 'app.cvent.com' || parsed.protocol !== 'https:' || parsed.username || parsed.password || (parsed.port && parsed.port !== '443') || eventKeyFromUrl(url) !== norm(eventKey)) {
    throw new Error('Trusted procedure refused a route outside the exact authorized event');
  }
  await ego.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await ego.waitForTimeout(650);
  return pageDisposition(ego, eventKey);
}

async function gridRows(ego) {
  return ego.evaluate(`(() => {const clean=v=>String(v||'').replace(/\\s+/g,' ').trim();return [...document.querySelectorAll('table tr,[role=row]')].map(row=>{const cells=[...row.querySelectorAll('th,td,[role=cell],[role=columnheader]')].map(cell=>clean(cell.innerText||cell.textContent));const links=[...row.querySelectorAll('a[href]')].map(link=>({text:clean(link.innerText||link.textContent),href:link.href}));return {text:clean(row.innerText||row.textContent),cells,links}}).filter(row=>row.cells.length)})()`);
}

function exactRow(rows, code) {
  const wanted = norm(code);
  const matches = rows.filter(row => row.cells.some(cell => norm(cell) === wanted));
  return matches.length === 1 ? { row: matches[0] } : { count: matches.length };
}

export function safeDetailHref(row, eventKey, pathNeedle) {
  const links = (row.links || []).filter(item => {
    try {
      const url = new URL(item.href);
      const paths = {
        admissionitem: /^\/subscribers\/events2\/agendaandfees\/admissionitemdetails(?:\/index(?:\/view)?)?\/?$/i,
        registrationtype: /^\/subscribers\/events2\/details\/registrationtypedetail\/index\/view\/?$/i,
      };
      const idName = { admissionitem: 'prodstub', registrationtype: 'registrationtypestub' }[pathNeedle];
      const ids = [...url.searchParams].filter(([name]) => name.toLowerCase() === idName).map(([, value]) => value.trim());
      return ids.length === 1 && Boolean(ids[0]) && url.protocol === 'https:' && url.hostname.toLowerCase() === 'app.cvent.com' &&
        !url.username && !url.password && (!url.port || url.port === '443') &&
        eventKeyFromUrl(item.href) === norm(eventKey) && Boolean(paths[pathNeedle]?.test(url.pathname));
    } catch { return false; }
  });
  return links.length === 1 ? links[0].href : null;
}

async function pageFacts(ego) {
  return ego.evaluate(`(() => {const clean=v=>String(v||'').replace(/\\s+/g,' ').trim();const label=element=>{const id=element.id;const direct=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):null;return clean(element.getAttribute('aria-label')||direct?.innerText||element.closest('label')?.innerText||element.getAttribute('name')||element.getAttribute('placeholder'))};return {title:document.title,body:String(document.body?.innerText||'').slice(0,500000),controls:[...document.querySelectorAll('input,select,textarea,[role=combobox]')].map(element=>({label:label(element),tag:element.tagName,type:(element.getAttribute('type')||'').toLowerCase(),value:(element.getAttribute('type')||'').toLowerCase()==='password'?null:('value' in element?String(element.value):''),checked:'checked' in element?Boolean(element.checked):null,disabled:'disabled' in element?Boolean(element.disabled):false})),buttons:[...document.querySelectorAll('button,[role=button],input[type=submit]')].map(element=>clean(element.innerText||element.value||element.getAttribute('aria-label'))).filter(Boolean)}})()`);
}

function textHasLabeledValue(body, labels, desired) {
  const lines = String(body || '').split(/\n+/).map(value => value.trim()).filter(Boolean);
  const wantedLabels = labels.map(norm);
  const wanted = norm(desired);
  for (let index = 0; index < lines.length; index += 1) {
    const line = norm(lines[index]);
    for (const label of wantedLabels) {
      if (line === label || line === `${label}:`) {
        if (norm(lines[index + 1]) === wanted) return true;
      }
      if (line.startsWith(`${label}:`) && norm(line.slice(label.length + 1)) === wanted) return true;
    }
  }
  return false;
}

async function markControl(ego, labels, kinds = []) {
  const marker = token();
  const result = await ego.evaluate(`(() => {const labels=${JSON.stringify(labels.map(norm))},kinds=${JSON.stringify(kinds)},marker=${JSON.stringify(marker)},clean=v=>String(v||'').replace(/\\s+/g,' ').trim().toLowerCase(),role=element=>element.getAttribute('role')||'',label=element=>{const id=element.id,direct=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):null;return clean(element.getAttribute('aria-label')||direct?.innerText||element.closest('label')?.innerText||element.getAttribute('name')||element.getAttribute('placeholder'))};const candidates=[...document.querySelectorAll('input,select,textarea,[role=combobox]')].filter(element=>element.isConnected&&!element.disabled&&labels.includes(label(element))&&(!kinds.length||kinds.includes((element.getAttribute('type')||element.tagName||role(element)).toLowerCase())));if(candidates.length!==1)return {count:candidates.length};candidates[0].setAttribute('data-cvent-trusted-target',marker);return {count:1,selector:'[data-cvent-trusted-target="'+marker+'"]',tag:candidates[0].tagName,type:(candidates[0].getAttribute('type')||'').toLowerCase(),value:'value' in candidates[0]?String(candidates[0].value):'',checked:'checked' in candidates[0]?Boolean(candidates[0].checked):null}})()`);
  return result.count === 1 ? result : null;
}

async function markButton(ego, labels) {
  const marker = token();
  const result = await ego.evaluate(`(() => {const wanted=${JSON.stringify(labels.map(norm))},marker=${JSON.stringify(marker)},clean=v=>String(v||'').replace(/\\s+/g,' ').trim().toLowerCase();const candidates=[...document.querySelectorAll('button,[role=button],input[type=submit],a[href]')].filter(element=>{const text=clean(element.innerText||element.value||element.getAttribute('aria-label'));const box=element.getBoundingClientRect(),style=getComputedStyle(element);return wanted.includes(text)&&element.isConnected&&!element.disabled&&box.width>0&&box.height>0&&style.display!=='none'&&style.visibility!=='hidden'});if(candidates.length!==1)return {count:candidates.length};candidates[0].setAttribute('data-cvent-trusted-target',marker);return {count:1,selector:'[data-cvent-trusted-target="'+marker+'"]'}})()`);
  return result.count === 1 ? result.selector : null;
}

async function setControl(ego, marked, desired) {
  if (!marked) return false;
  if (marked.type === 'checkbox' || marked.type === 'radio') {
    await ego.setChecked(marked.selector, Boolean(desired));
  } else if (marked.tag === 'SELECT') {
    await ego.selectOption(marked.selector, { label: String(desired) });
  } else {
    await ego.fill(marked.selector, String(desired));
  }
  return true;
}

async function chooseExactOption(ego, marked, desired) {
  if (!marked) return false;
  if (marked.tag === 'SELECT') return setControl(ego, marked, desired);
  await ego.click(marked.selector);
  await ego.waitForTimeout(250);
  const marker = token();
  const selected = await ego.evaluate(`(() => {const wanted=${JSON.stringify(norm(desired))},marker=${JSON.stringify(marker)},clean=v=>String(v||'').replace(/\\s+/g,' ').trim().toLowerCase();const matches=[...document.querySelectorAll('[role=option],li,[data-cvent-id*=option],[data-testid*=option]')].filter(element=>{const box=element.getBoundingClientRect(),style=getComputedStyle(element);return clean(element.innerText||element.textContent)===wanted&&element.isConnected&&box.width>0&&box.height>0&&style.display!=='none'&&style.visibility!=='hidden'});if(matches.length!==1)return {count:matches.length};matches[0].setAttribute('data-cvent-trusted-target',marker);return {count:1,selector:'[data-cvent-trusted-target="'+marker+'"]'}})()`);
  if (selected.count !== 1) return false;
  await ego.click(selected.selector);
  return true;
}

async function enterEdit(ego) {
  const edit = await markButton(ego, ['Edit']);
  if (!edit) return false;
  await ego.click(edit);
  await ego.waitForTimeout(650);
  return true;
}

async function save(ego) {
  const button = await markButton(ego, ['Save', 'Save and close', 'Save & close']);
  if (!button) return false;
  await ego.click(button);
  await ego.waitForTimeout(850);
  return true;
}

async function admissionAvailability(ego, expectedTypes, knownTypes) {
  const facts = await pageFacts(ego);
  const heading = 'limit which registration types can select this item';
  const lines = String(facts.body || '').split(/\n+/).map(value => value.trim()).filter(Boolean);
  const start = lines.findIndex(line => norm(line).replace(/:$/, '') === heading);
  if (start < 0) return { known: false };
  const tail = lines.slice(start + 1);
  const end = tail.findIndex(line => norm(line).replace(/:$/, '') === 'status & capacity');
  const section = norm((end < 0 ? tail : tail.slice(0, end)).join('\n'));
  if (/^no(?:\s|$)/.test(section)) return { known: true, allTypes: true, matches: expectedTypes.length === knownTypes.length };
  const selected = knownTypes.filter(item => section.includes(norm(item.name)) || section.includes(norm(item.code))).map(item => norm(item.code));
  const expected = expectedTypes.map(item => norm(item.code));
  const missing = expected.filter(item => !selected.includes(item));
  const unexpected = selected.filter(item => !expected.includes(item));
  return { known: true, allTypes: false, matches: missing.length === 0 && unexpected.length === 0, missing, unexpected };
}

async function markChoiceInSection(ego, heading, choice) {
  const marker = token();
  const result = await ego.evaluate(`(() => {const heading=${JSON.stringify(norm(heading))},choice=${JSON.stringify(norm(choice))},marker=${JSON.stringify(marker)},clean=v=>String(v||'').replace(/\\s+/g,' ').trim().toLowerCase(),all=[...document.querySelectorAll('h1,h2,h3,h4,label,legend,div,span')],anchor=all.find(element=>clean(element.innerText||element.textContent).replace(/:$/,'')===heading);if(!anchor)return {count:0};let root=anchor.parentElement;for(let depth=0;root&&depth<7;depth++,root=root.parentElement){const choices=[...root.querySelectorAll('input[type=radio],input[type=checkbox],button,[role=radio]')].filter(element=>{const id=element.id,direct=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):null,label=clean(direct?.innerText||element.closest('label')?.innerText||element.getAttribute('aria-label')||element.innerText);return label===choice&&element.isConnected&&!element.disabled});if(choices.length===1){choices[0].setAttribute('data-cvent-trusted-target',marker);return {count:1,selector:'[data-cvent-trusted-target="'+marker+'"]',type:(choices[0].getAttribute('type')||'').toLowerCase(),checked:'checked' in choices[0]?Boolean(choices[0].checked):null}}}return {count:0}})()`);
  return result.count === 1 ? result : null;
}

async function configureAdmissionAvailability(ego, expectedTypes, knownTypes) {
  const heading = 'Limit which registration types can select this item';
  const limiter = await markControl(ego, [`${heading}:`, heading], []);
  if (limiter) {
    if (!(await chooseExactOption(ego, limiter, 'Yes'))) return { ok: false, control: 'registration type availability limiter' };
  } else {
    const yes = await markChoiceInSection(ego, heading, 'Yes');
    if (!yes) return { ok: false, control: 'registration type availability limiter' };
    if (!yes.checked) {
      if (['radio', 'checkbox'].includes(yes.type)) await ego.setChecked(yes.selector, true);
      else await ego.click(yes.selector);
    }
  }
  await ego.waitForTimeout(300);
  const desired = new Set(expectedTypes.flatMap(item => [norm(item.code), norm(item.name)].filter(Boolean)));
  const known = new Set(knownTypes.flatMap(item => [norm(item.code), norm(item.name)].filter(Boolean)));
  const controls = await ego.evaluate(`(() => {const clean=v=>String(v||'').replace(/\\s+/g,' ').trim().toLowerCase(),result=[];for(const element of document.querySelectorAll('input[type=checkbox]')){const id=element.id,direct=id?document.querySelector('label[for="'+CSS.escape(id)+'"]'):null,label=clean(direct?.innerText||element.closest('label')?.innerText||element.getAttribute('aria-label'));if(label)result.push({label,checked:Boolean(element.checked)})}return result})()`);
  const relevant = controls.filter(item => known.has(norm(item.label)));
  if (relevant.length < knownTypes.length) return { ok: false, control: 'registration type checkboxes', found: relevant.map(item => item.label) };
  for (const item of knownTypes) {
    const marked = await markControl(ego, [item.name, item.code].filter(Boolean), ['checkbox']);
    if (!marked) return { ok: false, control: `registration type ${item.code}` };
    const shouldCheck = desired.has(norm(item.code)) || desired.has(norm(item.name));
    if (marked.checked !== shouldCheck) await ego.setChecked(marked.selector, shouldCheck);
  }
  return { ok: true };
}

async function configureAdmissionItems(ego, runtime, params) {
  const eventKey = runtime.authorizedEventKey;
  const gridUrl = `https://app.cvent.com/Subscribers/Events2/AgendaAndFees/AdmissionItemGrid/Index/?evtstub=${encodeURIComponent(eventKey)}`;
  let disposition = await gotoAuthorized(ego, gridUrl, eventKey);
  if (disposition.status) return { procedure: 'configureAdmissionItems', status: disposition.status, records: [], mutationCount: 0, page: disposition.page };
  let rows = await gridRows(ego);
  const records = [];
  let mutationCount = 0;
  for (const desired of params.records) {
    const found = exactRow(rows, desired.code);
    if (!found.row) {
      records.push({ reference: desired.code, status: found.count > 1 ? 'AMBIGUOUS' : 'CONTROL_NOT_FOUND', detail: `Admission grid exact-code matches: ${found.count || 0}` });
      continue;
    }
    const currentName = found.row.links?.[0]?.text || found.row.cells[0];
    const detailHref = safeDetailHref(found.row, eventKey, 'admissionitem');
    if (!detailHref) {
      records.push({ reference: desired.code, status: 'AMBIGUOUS', detail: 'Admission detail route was not unique and event-local' });
      continue;
    }
    disposition = await gotoAuthorized(ego, detailHref, eventKey);
    if (disposition.status) return { procedure: 'configureAdmissionItems', status: disposition.status, records, mutationCount, page: disposition.page };
    const availability = await admissionAvailability(ego, desired.registrationTypes || [], desired.knownRegistrationTypes || []);
    const nameMatches = norm(currentName) === norm(desired.name);
    if (nameMatches && availability.known && availability.matches) {
      records.push({ reference: desired.code, status: 'ALREADY_CORRECT', verified: ['name', 'code', 'registrationTypes'] });
      disposition = await gotoAuthorized(ego, gridUrl, eventKey); rows = await gridRows(ego);
      continue;
    }
    if (!(await enterEdit(ego))) {
      records.push({ reference: desired.code, status: 'CONTROL_NOT_FOUND', detail: 'Trusted Edit control not found' });
      disposition = await gotoAuthorized(ego, gridUrl, eventKey); rows = await gridRows(ego);
      continue;
    }
    disposition = await pageDisposition(ego, eventKey);
    if (disposition.status) return { procedure: 'configureAdmissionItems', status: disposition.status, records, mutationCount, page: disposition.page };
    const nameControl = nameMatches ? null : await markControl(ego, ['Name:', 'Name', 'Admission Item Name:', 'Admission Item Name']);
    if (!nameMatches && !nameControl) {
      records.push({ reference: desired.code, status: 'CONTROL_NOT_FOUND', detail: 'Trusted admission name control not found' });
      disposition = await gotoAuthorized(ego, gridUrl, eventKey); rows = await gridRows(ego);
      continue;
    }
    let association = { ok: true };
    if (!availability.known || !availability.matches) {
      association = await configureAdmissionAvailability(ego, desired.registrationTypes || [], desired.knownRegistrationTypes || []);
    }
    if (!association.ok) {
      records.push({ reference: desired.code, status: 'CONTROL_NOT_FOUND', configured: [], detail: association });
      disposition = await gotoAuthorized(ego, gridUrl, eventKey); rows = await gridRows(ego);
      continue;
    }
    if (!nameMatches) await setControl(ego, nameControl, desired.name);
    if (!nameMatches || !availability.matches) mutationCount += 1;
    disposition = await pageDisposition(ego, eventKey);
    if (disposition.status) throw new Error(`Exact event identity was lost before admission save for ${desired.code}`);
    if (!(await save(ego))) throw new Error(`Save control disappeared after admission mutation for ${desired.code}`);
    disposition = await gotoAuthorized(ego, gridUrl, eventKey);
    if (disposition.status) return { procedure: 'configureAdmissionItems', status: disposition.status, records, mutationCount, page: disposition.page };
    rows = await gridRows(ego);
    const verified = exactRow(rows, desired.code);
    const verifiedName = verified.row?.links?.[0]?.text || verified.row?.cells?.[0];
    if (!verified.row || norm(verifiedName) !== norm(desired.name)) {
      records.push({ reference: desired.code, status: 'VERIFY_FAILED', expectedName: desired.name, observedName: verifiedName || null });
    } else {
      const verifyHref = safeDetailHref(verified.row, eventKey, 'admissionitem');
      if (!verifyHref) {
        records.push({ reference: desired.code, status: 'VERIFY_FAILED', detail: 'Final admission detail route was not unique' });
      } else {
        disposition = await gotoAuthorized(ego, verifyHref, eventKey);
        if (disposition.status) return { procedure: 'configureAdmissionItems', status: disposition.status, records, mutationCount, page: disposition.page };
        const verifiedAvailability = await admissionAvailability(ego, desired.registrationTypes || [], desired.knownRegistrationTypes || []);
        records.push(verifiedAvailability.known && verifiedAvailability.matches ?
          { reference: desired.code, status: 'CONFIGURED', configured: [!nameMatches ? 'name' : null, !availability.matches ? 'registrationTypes' : null].filter(Boolean), verified: ['name', 'code', 'registrationTypes'] } :
          { reference: desired.code, status: 'VERIFY_FAILED', detail: 'Admission registration-type readback did not match', availability: verifiedAvailability });
        disposition = await gotoAuthorized(ego, gridUrl, eventKey); rows = await gridRows(ego);
      }
    }
  }
  const failures = records.filter(item => !['CONFIGURED', 'ALREADY_CORRECT'].includes(item.status));
  return { procedure: 'configureAdmissionItems', status: failures.length ? failures[0].status : (mutationCount ? 'CONFIGURED' : 'ALREADY_CORRECT'), records, mutationCount, finalVerification: { rowCount: rows.length, exactCodes: params.records.map(item => ({ code: item.code, matches: exactRow(rows, item.code).row ? 1 : exactRow(rows, item.code).count || 0 })) } };
}

export async function registrationFacts(ego, desired) {
  const facts = await pageFacts(ego);
  const feePattern = desired.reprintFee == null ? null : new RegExp(`reprint fee:?\\s*\\$?${String(Number(desired.reprintFee)).replace('.', '\\.')}(?:\\.00)?(?:\\s|$)`, 'i');
  const result = {
    active: textHasLabeledValue(facts.body, ['Active'], desired.active ? 'Yes' : 'No') ||
      textHasLabeledValue(facts.body, ['Status'], desired.active ? 'Active' : 'Inactive'),
    name: norm(facts.title) === norm(desired.name) || textHasLabeledValue(facts.body, ['Name'], desired.name),
    code: textHasLabeledValue(facts.body, ['Code', 'Registration Code'], desired.code),
    groupRegistration: desired.groupRegistration == null ? true : textHasLabeledValue(facts.body, ['Allow Group Registration?', 'Group Registration'], desired.groupRegistration ? 'Yes' : 'No'),
    reprintFee: desired.reprintFee == null ? true : textHasLabeledValue(facts.body, ['Reprint Fee'], String(desired.reprintFee)) || feePattern.test(String(facts.body)),
  };
  return { facts, matches: result, all: Object.values(result).every(Boolean) };
}

async function configureRegistrationTypes(ego, runtime, params) {
  const eventKey = runtime.authorizedEventKey;
  const gridUrl = `https://app.cvent.com/Subscribers/Events2/Details/RegistrationTypes/Index/View?evtstub=${encodeURIComponent(eventKey)}`;
  let disposition = await gotoAuthorized(ego, gridUrl, eventKey);
  if (disposition.status) return { procedure: 'configureRegistrationTypes', status: disposition.status, records: [], mutationCount: 0, page: disposition.page };
  let rows = await gridRows(ego);
  const records = [];
  let mutationCount = 0;
  for (const desired of params.records) {
    const found = exactRow(rows, desired.code);
    if (!found.row) {
      records.push({ reference: desired.code, status: found.count > 1 ? 'AMBIGUOUS' : 'CONTROL_NOT_FOUND', detail: `Registration-type grid exact-code matches: ${found.count || 0}` });
      continue;
    }
    const detailHref = safeDetailHref(found.row, eventKey, 'registrationtype');
    if (!detailHref) {
      records.push({ reference: desired.code, status: 'AMBIGUOUS', detail: 'Registration-type detail route was not unique and event-local' });
      continue;
    }
    disposition = await gotoAuthorized(ego, detailHref, eventKey);
    if (disposition.status) return { procedure: 'configureRegistrationTypes', status: disposition.status, records, mutationCount, page: disposition.page };
    const observed = await registrationFacts(ego, desired);
    if (observed.all) {
      records.push({ reference: desired.code, status: 'ALREADY_CORRECT', verified: Object.keys(observed.matches) });
      disposition = await gotoAuthorized(ego, gridUrl, eventKey); rows = await gridRows(ego);
      continue;
    }
    if (!(await enterEdit(ego))) {
      records.push({ reference: desired.code, status: 'CONTROL_NOT_FOUND', detail: 'Trusted Edit control not found', mismatches: observed.matches });
      disposition = await gotoAuthorized(ego, gridUrl, eventKey); rows = await gridRows(ego);
      continue;
    }
    disposition = await pageDisposition(ego, eventKey);
    if (disposition.status) return { procedure: 'configureRegistrationTypes', status: disposition.status, records, mutationCount, page: disposition.page };
    const changes = [];
    const planned = [];
    if (!observed.matches.name) planned.push({ field: 'name', marked: await markControl(ego, ['Name:', 'Name', 'Registration Type Name:', 'Registration Type Name']), value: desired.name });
    if (!observed.matches.groupRegistration) planned.push({ field: 'groupRegistration', marked: await markControl(ego, ['Allow Group Registration?:', 'Allow Group Registration?', 'Group Registration:', 'Group Registration']), value: desired.groupRegistration ? 'Yes' : 'No', option: true });
    if (!observed.matches.reprintFee) planned.push({ field: 'reprintFee', marked: await markControl(ego, ['Reprint Fee:', 'Reprint Fee']), value: desired.reprintFee });
    // Neither desired values nor incidental body substrings establish readback.
    // No reviewed active/code editor exists here: stop before any field mutation.
    const unavailable = [
      ...planned.filter(change => !change.marked),
      ...['active', 'code'].filter(field => !observed.matches[field]).map(field => ({ field })),
    ];
    if (unavailable.length) {
      records.push({ reference: desired.code, status: 'CONTROL_NOT_FOUND', detail: `Trusted controls absent: ${unavailable.map(item => item.field).join(', ')}`, mismatches: observed.matches });
      disposition = await gotoAuthorized(ego, gridUrl, eventKey); rows = await gridRows(ego);
      continue;
    }
    for (const change of planned) {
      const changed = change.option ? await chooseExactOption(ego, change.marked, change.value) : await setControl(ego, change.marked, change.value);
      if (!changed) throw new Error(`Trusted ${change.field} control changed shape after preflight for ${desired.code}`);
      changes.push(change.field); mutationCount += 1;
    }
    disposition = await pageDisposition(ego, eventKey);
    if (disposition.status) throw new Error(`Exact event identity was lost before registration-type save for ${desired.code}`);
    if (!(await save(ego))) throw new Error(`Save control disappeared after registration-type mutation for ${desired.code}`);
    disposition = await gotoAuthorized(ego, detailHref, eventKey);
    if (disposition.status) return { procedure: 'configureRegistrationTypes', status: disposition.status, records, mutationCount, page: disposition.page };
    const verified = await registrationFacts(ego, desired);
    records.push(verified.all ? { reference: desired.code, status: 'CONFIGURED', configured: changes, verified: Object.keys(verified.matches) } : { reference: desired.code, status: 'VERIFY_FAILED', configured: changes, mismatches: verified.matches });
    disposition = await gotoAuthorized(ego, gridUrl, eventKey); rows = await gridRows(ego);
  }
  const failures = records.filter(item => !['CONFIGURED', 'ALREADY_CORRECT'].includes(item.status));
  return { procedure: 'configureRegistrationTypes', status: failures.length ? failures[0].status : (mutationCount ? 'CONFIGURED' : 'ALREADY_CORRECT'), records, mutationCount, finalVerification: { rowCount: rows.length, exactCodes: params.records.map(item => ({ code: item.code, matches: exactRow(rows, item.code).row ? 1 : exactRow(rows, item.code).count || 0 })) } };
}

export async function runTrustedCventProcedure(ego, runtime, name, params) {
  if (!runtime?.authorizedEventKey) throw new Error('Trusted procedure requires the server-authorized event key');
  if (!Array.isArray(params?.records)) throw new Error('Trusted procedure requires typed RR records');
  let result;
  if (name === 'configureAdmissionItems') result = await configureAdmissionItems(ego, runtime, params);
  else if (name === 'configureRegistrationTypes') result = await configureRegistrationTypes(ego, runtime, params);
  else throw new Error(`Unknown trusted Cvent procedure: ${name}`);
  if (!STATUS.has(result.status)) throw new Error('Trusted procedure returned an invalid status');
  return result;
}
