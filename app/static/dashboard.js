"use strict";
const tbody = document.querySelector("#dataRows");
const status = document.querySelector("#status");
const help = document.querySelector("#help");
function cell(row, content) {
  const td = document.createElement("td");
  td.textContent = content === null || content === undefined ? "Not reported" : String(content);
  row.appendChild(td);
  return td;
}
async function load() {
  const country = document.querySelector("#country").value.toUpperCase().trim();
  const indicator = document.querySelector("#indicator").value;
  if (!/^[A-Z]{3}$/.test(country)) { status.textContent="Invalid country"; return; }
  status.textContent="Loading";
  const params = new URLSearchParams({country, indicator, limit:"100"});
  try {
    const response = await fetch("/v1/public/observations?" + params.toString(), {cache:"no-store"});
    if (!response.ok) throw new Error("API status " + response.status);
    const payload = await response.json();
    tbody.replaceChildren();
    if (payload.records.length === 0) {
      const tr = document.createElement("tr");
      cell(tr, "No imported observations for this query. Use the trusted operator ingestion command.");
      for (let i=0;i<5;i++) cell(tr,"");
      tbody.appendChild(tr);
    }
    for (const item of payload.records) {
      const row = document.createElement("tr");
      cell(row,item.country_code);
      cell(row,item.indicator_code);
      cell(row,item.period);
      const value = cell(row,item.value);
      value.className="value";
      const origin = document.createElement("td");
      const a = document.createElement("a");
      a.textContent=item.provider || "Source";
      if ((item.source_url || "").startsWith("https://api.worldbank.org/")) {
        a.href=item.source_url;
        a.target="_blank";
        a.rel="noopener noreferrer";
      }
      origin.appendChild(a);row.appendChild(origin);
      const stateCell = document.createElement("td");
      const state = document.createElement("span");
      state.className="state";state.textContent=item.provenance_state;
      stateCell.appendChild(state);row.appendChild(stateCell);
      tbody.appendChild(row);
    }
    status.textContent=payload.count+" source records";
    help.textContent="Provider-attributed data with stored SHA-256 digests and retrieval dates. No human finding is implied.";
  } catch {
    tbody.replaceChildren();const tr=document.createElement("tr");cell(tr,"Data service unavailable; verify /readyz.");tbody.appendChild(tr);
    status.textContent="Unavailable";
  }
}
document.querySelector("#filterForm").addEventListener("submit", (e) => {e.preventDefault(); load();});
load();

async function loadAwards() {
  const rows=document.querySelector("#awardRows");
  const el=document.querySelector("#awardStatus");
  try {
    const res=await fetch("/v1/public/awards?limit=30", {cache:"no-store"});
    if(!res.ok)throw Error("HTTP " + res.status);
    const payload=await res.json();
    rows.replaceChildren();
    if(!payload.records.length){
      const tr=document.createElement("tr");cell(tr,"No award pages imported yet.");
      for(let i=0;i<4;i++)cell(tr,"");rows.appendChild(tr);
    }
    for(const a of payload.records){
      const row=document.createElement("tr");
      cell(row,a.external_award_id||a.source_award_key);
      cell(row,a.awarding_agency);
      cell(row,a.recipient_name);
      const amount=cell(row,a.award_amount===null?"Not reported":a.award_amount+" "+a.currency);
      amount.className="value";
      const linkCell=document.createElement("td");
      const link=document.createElement("a");
      link.href="/v1/public/awards/"+encodeURIComponent(a.id)+"/provenance";
      link.textContent="Provenance"; link.target="_blank";link.rel="noopener noreferrer";
      linkCell.appendChild(link);row.appendChild(linkCell);rows.appendChild(row);
    }
    el.textContent=payload.count+" award records";
  }catch{
    rows.replaceChildren();const tr=document.createElement("tr");cell(tr,"Award data service unavailable.");rows.appendChild(tr);
    el.textContent="Unavailable";
  }
}
loadAwards();
