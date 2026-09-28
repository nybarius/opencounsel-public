const views = {
  intake: document.querySelector("#intake-view"),
  processing: document.querySelector("#processing-view"),
  results: document.querySelector("#results-view"),
  error: document.querySelector("#error-view"),
};

const form = document.querySelector("#intake-form");
const briefInput = document.querySelector("#brief-input");
const roaInput = document.querySelector("#roa-input");
const roaDropzone = document.querySelector("#roa-dropzone");
const profileSelect = document.querySelector("#profile");
const prepareButton = document.querySelector("#prepare-button");
const demoButton = document.querySelector("#demo-button");
const pdfOptions = document.querySelector("#pdf-options");
const sourceUploadForm = document.querySelector("#source-upload-form");
const sourceUploadList = document.querySelector("#source-upload-list");
const verifySourcesButton = document.querySelector("#verify-sources");
const linkReview = document.querySelector("#link-review");
const linkList = document.querySelector("#link-list");
const approveLinksButton = document.querySelector("#approve-links");
const pdfPreview = document.querySelector("#pdf-preview");
const previewBeforeButton = document.querySelector("#preview-before");
const previewPreparedButton = document.querySelector("#preview-prepared");
let profiles = [];
let pollTimer = null;
let activeJobId = null;
let activeJob = null;

function showView(name) {
  Object.entries(views).forEach(([key, element]) => {
    element.hidden = key !== name;
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function setFileState(input, zoneId, nameId) {
  const file = input.files[0];
  const zone = document.querySelector(zoneId);
  const label = document.querySelector(nameId);
  zone.classList.toggle("has-file", Boolean(file));
  label.textContent = file ? file.name : "No file selected";
}

function wireDropzone(input, zoneId, nameId) {
  const zone = document.querySelector(zoneId);
  input.addEventListener("change", () => setFileState(input, zoneId, nameId));
  ["dragenter", "dragover"].forEach((eventName) => {
    zone.addEventListener(eventName, () => zone.classList.add("dragging"));
  });
  ["dragleave", "drop"].forEach((eventName) => {
    zone.addEventListener(eventName, () => zone.classList.remove("dragging"));
  });
}

wireDropzone(briefInput, "#brief-dropzone", "#brief-name");
wireDropzone(roaInput, "#roa-dropzone", "#roa-name");

function recordMode() {
  return document.querySelector("input[name='record_mode']:checked")?.value || "record";
}

function updateRecordMode() {
  const usesRecord = recordMode() === "record";
  roaInput.required = usesRecord;
  roaInput.disabled = !usesRecord;
  roaDropzone.hidden = !usesRecord;
  if (!usesRecord) {
    roaInput.value = "";
    setFileState(roaInput, "#roa-dropzone", "#roa-name");
  }
  updatePdfOptions();
}

function updatePdfOptions() {
  const isPdf = recordMode() === "record"
    && roaInput.files[0]?.name.toLowerCase().endsWith(".pdf");
  pdfOptions.hidden = !isPdf;
  document.querySelector("#numbering-verified").required = Boolean(isPdf);
}

document.querySelectorAll("input[name='record_mode']").forEach((input) => {
  input.addEventListener("change", updateRecordMode);
});
roaInput.addEventListener("change", updatePdfOptions);
updateRecordMode();

profileSelect.addEventListener("change", () => {
  const profile = profiles.find((item) => item.profile_id === profileSelect.value);
  if (!profile) return;
  document.querySelector("#body-rule").textContent = `${formatNumber(profile.body_font_pt)} pt`;
  document.querySelector("#footnote-rule").textContent = `${formatNumber(profile.footnote_font_pt)} pt`;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!form.reportValidity()) return;
  setBusy(true);
  try {
    const response = await fetch("/api/jobs", { method: "POST", body: new FormData(form) });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The filing inputs were not accepted.");
    showView("processing");
    await pollJob(payload.job_id);
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
  }
});

demoButton.addEventListener("click", async () => {
  setBusy(true);
  try {
    const response = await fetch("/api/demo", { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The demonstration could not start.");
    showView("processing");
    await pollJob(payload.job_id);
  } catch (error) {
    showError(error.message);
  } finally {
    setBusy(false);
  }
});

async function pollJob(jobId) {
  if (pollTimer) window.clearTimeout(pollTimer);
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
  const job = await response.json();
  if (!response.ok) {
    showError(job.error || "The job could not be loaded.");
    return;
  }
  renderProgress(job);
  if (job.status === "completed") {
    renderResults(job);
    showView("results");
    return;
  }
  if (job.status === "failed") {
    showError(job.error || "OpenCounsel could not prepare this filing.");
    return;
  }
  await new Promise((resolve) => {
    pollTimer = window.setTimeout(resolve, 650);
  });
  await pollJob(jobId);
}

function renderProgress(job) {
  document.querySelector("#processing-message").textContent = job.message;
  const list = document.querySelector("#progress-list");
  list.replaceChildren(...job.stages.map((stage, index) => {
    const item = document.createElement("li");
    item.className = stage.status;
    const mark = document.createElement("span");
    mark.className = "stage-mark";
    mark.textContent = stage.status === "completed" ? "✓" : String(index + 1).padStart(2, "0");
    const label = document.createElement("span");
    label.textContent = stage.label;
    item.append(mark, label);
    return item;
  }));
}

function renderResults(job) {
  activeJobId = job.job_id;
  activeJob = job;
  const summary = job.summary || {};
  const resolved = summary.resolved_record_citation_count || 0;
  const recordCount = summary.record_citation_count || 0;
  const metrics = [
    ["Record citations", `${resolved}/${recordCount}`, summary.unresolved_record_citation_count ? "Review unresolved cites" : "All resolved"],
    ["TOA authorities", summary.toa_authority_count || 0, `${summary.toa_occurrence_count || 0} occurrences`],
    ["TOC entries", summary.toc_entry_count || 0, "Linked and paginated"],
    ["Publication", `${summary.page_count || 0} pages`, "DOCX and PDF verified"],
  ];
  document.querySelector("#metric-grid").replaceChildren(...metrics.map(metricCard));

  setArtifact("#download-package", job, "package");
  setArtifact("#download-document", job, "document");
  setArtifact("#download-pdf", job, "pdf");
  setArtifact("#download-original-pdf", job, "original-pdf");
  setArtifact("#download-corrections", job, "corrections");
  setArtifact("#download-conformance", job, "conformance");
  setArtifact("#download-process", job, "process");
  setArtifact("#download-sources", job, "sources");
  setArtifact("#download-roa-package", job, "roa-package");
  setArtifact("#source-report-link", job, "sources");
  setArtifact("#download-final-package", job, "final-package");
  setArtifact("#download-linked-document", job, "linked-document");
  setArtifact("#download-linked-pdf", job, "linked-pdf");
  previewBeforeButton.hidden = !job.artifacts?.["original-pdf"];
  showPreview("pdf");

  const reviewItems = [
    ["Ledger items", summary.review_item_count || 0, "Every proposed or review-only finding remains visible."],
    ["Source copies requested", summary.source_copy_required_count || 0, "Opinion copies needed for substantive verification."],
    ["Unresolved record cites", summary.unresolved_record_citation_count || 0, "Blocking record references that did not resolve."],
  ];
  document.querySelector("#review-count").textContent = `${summary.review_item_count || 0} ledger items`;
  document.querySelector("#review-summary").replaceChildren(...reviewItems.map(reviewCard));

  renderSourceTable(job.sources || []);
  renderSourceUploads(job.sources || []);
  renderWhy(job);
  renderLinkReview(job.link_disposition);

  document.querySelector("#profile-name").textContent = job.profile?.court || "Applied profile";
  const formats = [
    ["Body text", `${formatNumber(summary.body_font_pt || 0)} pt`, "Enforced by filing profile"],
    ["Footnotes", `${formatNumber(summary.footnote_font_pt || 0)} pt`, "Separate note style"],
    ["Styles normalized", summary.formatting_applied_count || 0, "Reviewable applications"],
    ["Authority links", summary.hyperlink_inserted_count || 0, "Approved targets inserted"],
    ["TOC", `${summary.toc_entry_count || 0} entries`, "Static linked page labels"],
    ["TOA", `${summary.toa_authority_count || 0} authorities`, "Deduplicated page references"],
  ];
  document.querySelector("#formatting-grid").replaceChildren(...formats.map(metricCard));

  const audit = job.audit || {};
  const auditItems = [
    ["Input brief", audit.input_sha256 || "Not reported"],
    ["Prepared DOCX", audit.output_docx_sha256 || "Not reported"],
    ["Reference PDF", audit.output_pdf_sha256 || "Not reported"],
    ["Process", audit.process_id || "Local demonstration"],
    ["Layout engine", `${audit.engine || "LibreOffice"} ${audit.engine_version || ""}`.trim()],
  ];
  document.querySelector("#audit-list").replaceChildren(...auditItems.map(auditRow));

  const finalized = Boolean(job.artifacts?.["final-package"]);
  document.querySelector("#results-title").textContent = finalized
    ? "Source-verified package ready for lawyer review"
    : "Prepared — lawyer review required";
  document.querySelector("#results-lede").textContent = finalized
    ? "Identity and quotation checks are complete. Review characterization and the final linked copies."
    : "Review the prepared filing, then supply any requested opinions to complete source verification.";
}

async function renderWhy(job) {
  const list = document.querySelector("#why-list");
  if (!list) return;
  list.replaceChildren();
  const record = job.artifacts?.corrections;
  if (!record) {
    list.textContent = "No ledger items yet.";
    return;
  }
  let ledger;
  try {
    const response = await fetch(artifactUrl(job.job_id, "corrections", true));
    ledger = await response.json();
  } catch (error) {
    list.textContent = "UNOBSERVED: the correction ledger could not be read.";
    return;
  }
  const items = Array.isArray(ledger) ? ledger : ledger.corrections || ledger.items || [];
  for (const item of items.slice(0, 200)) {
    const response = await fetch("/api/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(item),
    });
    const lifted = response.ok ? await response.json() : { prose: "UNOBSERVED", witness: "" };
    const card = document.createElement("article");
    card.className = "review-card";
    const prose = document.createElement("p");
    prose.textContent = lifted.prose;
    const witness = document.createElement("p");
    witness.className = "review-note";
    witness.textContent = lifted.witness ? `Witness: ${lifted.witness}` : "";
    const receipt = document.createElement("details");
    const receiptTitle = document.createElement("summary");
    receiptTitle.textContent = "View ledger receipt";
    const receiptFields = document.createElement("dl");
    receiptFields.replaceChildren(...[
      ["Process", ledger.process_id || job.audit?.process_id || "Not reported"],
      ["Correction", item.correction_id || "Not reported"],
      ["Ledger SHA-256", record.sha256 || "Not reported"],
    ].map(auditRow));
    const receiptLink = document.createElement("a");
    receiptLink.href = artifactUrl(job.job_id, "corrections");
    receiptLink.textContent = "Download correction ledger";
    receipt.append(receiptTitle, receiptFields, receiptLink);
    card.append(prose, witness, receipt);
    list.append(card);
  }
}

function metricCard([label, value, note]) {
  const card = document.createElement("div");
  card.className = "metric-card";
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value;
  const noteNode = document.createElement("small");
  noteNode.textContent = note;
  card.append(labelNode, valueNode, noteNode);
  return card;
}

function reviewCard([label, value, note]) {
  const item = document.createElement("article");
  item.className = "review-item";
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value;
  const noteNode = document.createElement("p");
  noteNode.textContent = note;
  item.append(labelNode, valueNode, noteNode);
  return item;
}

function renderSourceTable(sources) {
  const table = document.querySelector("#source-table");
  if (!sources.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 3;
    cell.textContent = "No authorities were detected.";
    row.append(cell);
    table.replaceChildren(row);
    return;
  }
  table.replaceChildren(...sources.map((source) => {
    const row = document.createElement("tr");
    const citation = document.createElement("td");
    citation.className = "source-citation";
    citation.textContent = source.citation;
    const count = document.createElement("td");
    count.textContent = source.occurrence_count;
    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    const verified = source.status === "verified-source";
    const available = source.status === "official-or-open-source";
    status.className = `source-status ${verified || available ? "available" : "requested"}`;
    status.textContent = verified
      ? "Verified source"
      : available ? "Official/open source" : "Source copy requested";
    statusCell.append(status);
    row.append(citation, count, statusCell);
    return row;
  }));
}

function renderSourceUploads(sources) {
  const requested = sources.filter((source) => source.status === "source-copy-required");
  sourceUploadForm.hidden = requested.length === 0 || Boolean(activeJob?.source_verification);
  sourceUploadList.replaceChildren(...requested.map((source) => {
    const label = document.createElement("label");
    label.className = "review-item";
    const citation = document.createElement("strong");
    citation.textContent = source.citation;
    const identifier = document.createElement("span");
    identifier.textContent = source.authority_id;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pdf,application/pdf";
    input.required = true;
    input.dataset.authorityId = source.authority_id;
    label.append(citation, identifier, input);
    return label;
  }));
}

function renderLinkReview(disposition) {
  const links = disposition?.links || [];
  linkReview.hidden = !disposition;
  linkList.replaceChildren(...links.map((link) => {
    const label = document.createElement("label");
    label.className = "review-item";
    const title = document.createElement("strong");
    title.textContent = link.original_target_url;
    const status = document.createElement("span");
    status.textContent = `${link.classification} — ${link.approval_status}`;
    label.append(title, status);
    if (link.classification === "durable-candidate" && link.approval_status === "pending") {
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = link.link_id;
      input.dataset.linkId = link.link_id;
      label.prepend(input);
    }
    return label;
  }));
  const pending = links.some((link) => link.approval_status === "pending");
  approveLinksButton.hidden = !pending;
}

sourceUploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const inputs = [...sourceUploadList.querySelectorAll("input[type='file']")];
  if (!inputs.every((input) => input.files.length === 1)) return;
  verifySourcesButton.disabled = true;
  try {
    const data = new FormData();
    inputs.forEach((input) => {
      data.append("authority_id", input.dataset.authorityId);
      data.append("source", input.files[0]);
    });
    const response = await fetch(`/api/jobs/${encodeURIComponent(activeJobId)}/sources`, {
      method: "POST",
      body: data,
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The source PDFs were not accepted.");
    renderResults(payload);
  } catch (error) {
    showError(error.message);
  } finally {
    verifySourcesButton.disabled = false;
  }
});

approveLinksButton.addEventListener("click", async () => {
  const link_ids = [...linkList.querySelectorAll("input[data-link-id]:checked")]
    .map((input) => input.dataset.linkId);
  if (!link_ids.length) return;
  approveLinksButton.disabled = true;
  try {
    const response = await fetch(`/api/jobs/${encodeURIComponent(activeJobId)}/links`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ link_ids }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "The selected links were not approved.");
    renderResults(payload);
  } catch (error) {
    showError(error.message);
  } finally {
    approveLinksButton.disabled = false;
  }
});

function auditRow([label, value]) {
  const row = document.createElement("div");
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value;
  row.append(term, description);
  return row;
}

function setArtifact(selector, job, key) {
  const link = document.querySelector(selector);
  if (job.artifacts?.[key]) {
    link.href = artifactUrl(job.job_id, key, false);
    link.hidden = false;
  } else {
    link.hidden = true;
  }
}

function artifactUrl(jobId, key, inline) {
  return `/api/jobs/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(key)}${inline ? "?inline=1" : ""}`;
}

function showPreview(key) {
  if (!activeJob?.artifacts?.[key]) return;
  const before = key === "original-pdf";
  pdfPreview.src = artifactUrl(activeJob.job_id, key, true);
  pdfPreview.title = before
    ? "Original brief PDF preview"
    : "Prepared filing PDF preview";
  document.querySelector("#preview-label").textContent = before
    ? "Original uploaded brief"
    : "Prepared filing";
  previewBeforeButton.setAttribute("aria-pressed", String(before));
  previewPreparedButton.setAttribute("aria-pressed", String(!before));
}

function showError(message) {
  document.querySelector("#error-message").textContent = message;
  showView("error");
}

function reset() {
  if (pollTimer) window.clearTimeout(pollTimer);
  form.reset();
  activeJobId = null;
  activeJob = null;
  pdfPreview.removeAttribute("src");
  setFileState(briefInput, "#brief-dropzone", "#brief-name");
  setFileState(roaInput, "#roa-dropzone", "#roa-name");
  updateRecordMode();
  showView("intake");
}

function setBusy(busy) {
  prepareButton.disabled = busy;
  demoButton.disabled = busy;
  prepareButton.textContent = busy ? "Preparing…" : "Prepare first pass";
}

function formatNumber(value) {
  return Number.isInteger(Number(value)) ? String(Number(value)) : String(value);
}

document.querySelector("#new-job").addEventListener("click", reset);
document.querySelector("#try-again").addEventListener("click", reset);
previewBeforeButton.addEventListener("click", () => showPreview("original-pdf"));
previewPreparedButton.addEventListener("click", () => showPreview("pdf"));
document.querySelector("#delete-job").addEventListener("click", async () => {
  if (!activeJobId) return;
  const confirmed = window.confirm(
    "Delete the uploaded files and every generated artifact for this local job?"
  );
  if (!confirmed) return;
  const response = await fetch(`/api/jobs/${encodeURIComponent(activeJobId)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const payload = await response.json();
    showError(payload.error || "The local job could not be deleted.");
    return;
  }
  reset();
});

document.querySelectorAll("[role='tab']").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("[role='tab']").forEach((candidate) => {
      const selected = candidate === tab;
      candidate.setAttribute("aria-selected", String(selected));
      document.querySelector(`#${candidate.getAttribute("aria-controls")}`).hidden = !selected;
    });
  });
});

async function loadProfiles() {
  try {
    const response = await fetch("/api/profiles");
    const payload = await response.json();
    if (!response.ok) throw new Error("Filing profiles are unavailable.");
    profiles = payload.profiles;
    profileSelect.replaceChildren(...profiles.map((profile) => {
      const option = document.createElement("option");
      option.value = profile.profile_id;
      option.textContent = `${profile.court} — ${profile.document_type.replaceAll("-", " ")}`;
      option.selected = profile.profile_id === "ny-ad-appellant-brief";
      return option;
    }));
    profileSelect.dispatchEvent(new Event("change"));
  } catch (_error) {
    profileSelect.replaceChildren();
    const option = document.createElement("option");
    option.textContent = "Filing profiles unavailable";
    profileSelect.append(option);
    prepareButton.disabled = true;
  }
}

loadProfiles();
