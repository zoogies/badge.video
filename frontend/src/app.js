const STATE_FIPS = {
  "01": ["AL", "Alabama"], "02": ["AK", "Alaska"], "04": ["AZ", "Arizona"], "05": ["AR", "Arkansas"],
  "06": ["CA", "California"], "08": ["CO", "Colorado"], "09": ["CT", "Connecticut"], "10": ["DE", "Delaware"],
  "11": ["DC", "District of Columbia"], "12": ["FL", "Florida"], "13": ["GA", "Georgia"], "15": ["HI", "Hawaii"],
  "16": ["ID", "Idaho"], "17": ["IL", "Illinois"], "18": ["IN", "Indiana"], "19": ["IA", "Iowa"],
  "20": ["KS", "Kansas"], "21": ["KY", "Kentucky"], "22": ["LA", "Louisiana"], "23": ["ME", "Maine"],
  "24": ["MD", "Maryland"], "25": ["MA", "Massachusetts"], "26": ["MI", "Michigan"], "27": ["MN", "Minnesota"],
  "28": ["MS", "Mississippi"], "29": ["MO", "Missouri"], "30": ["MT", "Montana"], "31": ["NE", "Nebraska"],
  "32": ["NV", "Nevada"], "33": ["NH", "New Hampshire"], "34": ["NJ", "New Jersey"], "35": ["NM", "New Mexico"],
  "36": ["NY", "New York"], "37": ["NC", "North Carolina"], "38": ["ND", "North Dakota"], "39": ["OH", "Ohio"],
  "40": ["OK", "Oklahoma"], "41": ["OR", "Oregon"], "42": ["PA", "Pennsylvania"], "44": ["RI", "Rhode Island"],
  "45": ["SC", "South Carolina"], "46": ["SD", "South Dakota"], "47": ["TN", "Tennessee"], "48": ["TX", "Texas"],
  "49": ["UT", "Utah"], "50": ["VT", "Vermont"], "51": ["VA", "Virginia"], "53": ["WA", "Washington"],
  "54": ["WV", "West Virginia"], "55": ["WI", "Wisconsin"], "56": ["WY", "Wyoming"],
};

const STATE_NAME_TO_ABBR = Object.fromEntries(Object.values(STATE_FIPS).map(([abbr, name]) => [name.toLowerCase(), abbr]));
const STATE_ABBR_TO_NAME = Object.fromEntries(Object.values(STATE_FIPS));

const els = {
  generatedAt: document.querySelector("#generatedAt"),
  recordCount: document.querySelector("#recordCount"),
  randomButton: document.querySelector("#randomButton"),
  searchInput: document.querySelector("#searchInput"),
  stateFilter: document.querySelector("#stateFilter"),
  countyFilter: document.querySelector("#countyFilter"),
  crimeFilter: document.querySelector("#crimeFilter"),
  reviewFilter: document.querySelector("#reviewFilter"),
  sortSelect: document.querySelector("#sortSelect"),
  mapMode: document.querySelector("#mapMode"),
  mapSvg: document.querySelector("#mapSvg"),
  mapLayer: document.querySelector("#mapLayer"),
  stateLayer: document.querySelector("#stateLayer"),
  countyLayer: document.querySelector("#countyLayer"),
  mapTooltip: document.querySelector("#mapTooltip"),
  clearMapButton: document.querySelector("#clearMapButton"),
  resetViewButton: document.querySelector("#resetViewButton"),
  resultSummary: document.querySelector("#resultSummary"),
  videoList: document.querySelector("#videoList"),
  detailEmpty: document.querySelector("#detailEmpty"),
  detailContent: document.querySelector("#detailContent"),
};

let allVideos = [];
let countyGeoJson = null;
let stateGeoJson = null;
let selectedVideoId = null;
let mapPath = null;
let mapZoom = null;
let editDraft = null;
let listScrollTop = 0;
let scrollSelectedIntoView = false;
let randomSortOrder = new Map();

async function boot() {
  const [videoResponse, countyResponse, stateResponse] = await Promise.all([
    fetch("./public/data/videos.index.json", { cache: "no-store" }),
    fetch("./public/data/us-counties-fips.geojson", { cache: "force-cache" }),
    fetch("./public/data/us-states.geojson", { cache: "force-cache" }),
  ]);
  if (!videoResponse.ok) throw new Error(`Failed to load videos.index.json: ${videoResponse.status}`);
  if (!countyResponse.ok) throw new Error(`Failed to load us-counties-fips.geojson: ${countyResponse.status}`);
  if (!stateResponse.ok) throw new Error(`Failed to load us-states.geojson: ${stateResponse.status}`);

  const data = await videoResponse.json();
  countyGeoJson = await countyResponse.json();
  stateGeoJson = await stateResponse.json();
  allVideos = data.videos || [];
  els.generatedAt.textContent = `Generated ${formatDateTime(data.generated_at)}`;
  els.recordCount.textContent = `${allVideos.length.toLocaleString()} classified videos`;

  fillSelect(els.stateFilter, "All states", uniqueValues(allVideos.map(video => stateNameFromVideo(video))));
  fillCountyFilter();
  fillSelect(els.crimeFilter, "All crimes", uniqueValues(allVideos.flatMap(video => video.crime_categories || [])));
  initMap();
  render();
}

function initMap() {
  const svg = d3.select(els.mapSvg);
  mapZoom = d3.zoom()
    .scaleExtent([1, 9])
    .on("zoom", event => {
      d3.select(els.mapLayer).attr("transform", event.transform);
    });
  svg.call(mapZoom);
  window.addEventListener("resize", debounce(() => {
    fitMapProjection();
    render();
  }, 150));
  fitMapProjection();
}

function fitMapProjection() {
  const bounds = els.mapSvg.getBoundingClientRect();
  const width = Math.max(320, bounds.width);
  const height = Math.max(280, bounds.height);
  els.mapSvg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const projection = d3.geoAlbersUsa().fitSize([width, height], countyGeoJson);
  mapPath = d3.geoPath(projection);
}

function render() {
  listScrollTop = els.videoList.scrollTop;
  fillCountyFilter();
  const filtered = getFilteredVideos();
  renderMap(filtered);
  renderList(filtered);
  renderDetail(filtered.find(video => video.video_id === selectedVideoId) || null);
  els.videoList.scrollTop = listScrollTop;
}

function getFilteredVideos() {
  const query = els.searchInput.value.trim().toLowerCase();
  const state = els.stateFilter.value;
  const county = els.countyFilter.value;
  const crime = els.crimeFilter.value;
  const review = els.reviewFilter.value;
  const filtered = allVideos.filter(video => {
    if (state && stateNameFromVideo(video) !== state) return false;
    if (county && normalizeCounty(video.county) !== county) return false;
    if (crime && !(video.crime_categories || []).includes(crime)) return false;
    if (review === "needs_review" && video.human_reviewed) return false;
    if (review === "reviewed" && !video.human_reviewed) return false;
    if (!query) return true;
    return searchableText(video).includes(query);
  });
  return sortVideos(filtered, els.sortSelect.value);
}

function renderMap(videos) {
  if (!countyGeoJson || !mapPath) return;

  const stateCounts = new Map();
  const countyCounts = new Map();
  for (const video of videos) {
    const abbr = stateAbbrFromVideo(video);
    if (abbr) stateCounts.set(abbr, (stateCounts.get(abbr) || 0) + 1);
    const countyKey = countyKeyFromVideo(video);
    if (countyKey) countyCounts.set(countyKey, (countyCounts.get(countyKey) || 0) + 1);
  }

  const mode = els.mapMode.value;
  const max = Math.max(1, ...Array.from(mode === "counties" ? countyCounts.values() : stateCounts.values()));
  const selectedState = els.stateFilter.value;
  const selectedCounty = els.countyFilter.value;

  renderStateLayer(selectedState);
  renderCountyLayer(mode, stateCounts, countyCounts, max, selectedState, selectedCounty);
}

function renderStateLayer(selectedState) {
  const states = d3.select(els.stateLayer)
    .selectAll("path")
    .data(stateGeoJson.features, feature => feature.id);

  states.enter()
    .append("path")
    .attr("class", "stateShape")
    .merge(states)
    .attr("d", mapPath)
    .classed("selected", feature => selectedState && stateNameFromStateFeature(feature) === selectedState);

  states.exit().remove();
}

function renderCountyLayer(mode, stateCounts, countyCounts, max, selectedState, selectedCounty) {
  const paths = d3.select(els.mapLayer)
    .select("#countyLayer")
    .selectAll("path")
    .data(countyGeoJson.features, feature => feature.id);

  paths.enter()
    .append("path")
    .attr("class", "countyShape")
    .merge(paths)
    .attr("d", mapPath)
    .attr("data-state", feature => stateNameFromFeature(feature))
    .attr("data-county", feature => normalizeCounty(feature.properties.NAME))
    .style("--map-fill", feature => {
      const count = featureCount(feature, mode, stateCounts, countyCounts);
      return heatColor(count / max, count > 0);
    })
    .classed("hasData", feature => featureCount(feature, mode, stateCounts, countyCounts) > 0)
    .classed("selected", feature => {
      const stateMatch = selectedState && stateNameFromFeature(feature) === selectedState;
      const countyMatch = selectedCounty && normalizeCounty(feature.properties.NAME) === selectedCounty;
      return Boolean(mode === "states" ? stateMatch : stateMatch && (!selectedCounty || countyMatch));
    })
    .on("mousemove", (event, feature) => showTooltip(event, feature, mode, stateCounts, countyCounts))
    .on("mouseleave", hideTooltip)
    .on("click", (event, feature) => selectMapFeature(feature, mode));

  paths.exit().remove();
}

function featureCount(feature, mode, stateCounts, countyCounts) {
  const abbr = stateAbbrFromFeature(feature);
  if (mode === "counties") return countyCounts.get(countyKeyFromFeature(feature)) || 0;
  return stateCounts.get(abbr) || 0;
}

function selectMapFeature(feature, mode) {
  const stateName = stateNameFromFeature(feature);
  const county = normalizeCounty(feature.properties.NAME);
  if (mode === "counties") {
    els.stateFilter.value = stateName;
    fillCountyFilter();
    els.countyFilter.value = county;
  } else {
    els.stateFilter.value = els.stateFilter.value === stateName ? "" : stateName;
    els.countyFilter.value = "";
    fillCountyFilter();
  }
  render();
}

function showTooltip(event, feature, mode, stateCounts, countyCounts) {
  const state = stateNameFromFeature(feature);
  const county = feature.properties.NAME;
  const count = featureCount(feature, mode, stateCounts, countyCounts);
  els.mapTooltip.innerHTML = `
    <strong>${escapeHtml(mode === "counties" ? `${county} County` : state)}</strong>
    <span>${count.toLocaleString()} matching videos</span>
  `;
  els.mapTooltip.classList.remove("hidden");
  const panel = els.mapSvg.getBoundingClientRect();
  els.mapTooltip.style.left = `${event.clientX - panel.left + 14}px`;
  els.mapTooltip.style.top = `${event.clientY - panel.top + 14}px`;
}

function hideTooltip() {
  els.mapTooltip.classList.add("hidden");
}

function renderList(videos) {
  els.resultSummary.textContent = `${videos.length.toLocaleString()} matching videos`;
  const rows = videos.slice(0, 250).map(video => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "videoRow";
    row.dataset.videoId = video.video_id;
    row.classList.toggle("selected", video.video_id === selectedVideoId);
    row.addEventListener("click", () => {
      listScrollTop = els.videoList.scrollTop;
      selectedVideoId = video.video_id;
      render();
    });
    row.innerHTML = `
      <div class="rowMain">
        <span class="title">${escapeHtml(video.title)}</span>
        <span class="meta">${escapeHtml(locationLine(video))} - ${formatDate(video.published_at)}</span>
        <span class="rowTags">
          ${dedupeLabels(video.crime_categories).slice(0, 4).map(tag => `<span>${escapeHtml(displayLabel(tag))}</span>`).join("")}
        </span>
      </div>
      <div class="reviewDot ${video.human_reviewed ? "reviewed" : ""}" title="${video.human_reviewed ? "Human reviewed" : "Needs review"}"></div>
    `;
    return row;
  });
  els.videoList.replaceChildren(...rows);
  if (scrollSelectedIntoView) {
    const selectedRow = els.videoList.querySelector(`[data-video-id="${escapeSelector(selectedVideoId)}"]`);
    selectedRow?.scrollIntoView({ block: "center" });
    scrollSelectedIntoView = false;
    listScrollTop = els.videoList.scrollTop;
  }
}

function renderDetail(video) {
  if (!video) {
  els.detailEmpty.classList.remove("hidden");
    els.detailContent.classList.add("hidden");
    els.detailContent.replaceChildren();
    return;
  }
  els.detailEmpty.classList.add("hidden");
  els.detailContent.classList.remove("hidden");
  const draft = getDraft(video);
  const changed = draftChanged(video);
  els.detailContent.innerHTML = `
    <div class="detailHeader">
      <div>
        <h2>${escapeHtml(video.title)}</h2>
        <p>${escapeHtml(video.channel || "Unknown channel")}</p>
      </div>
      <a class="iconButton" href="${escapeAttribute(video.url)}" target="_blank" rel="noreferrer" title="Open video in new tab" aria-label="Open video in new tab">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M14 3h7v7"></path>
          <path d="M10 14 21 3"></path>
          <path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"></path>
        </svg>
      </a>
    </div>
    <div class="videoEmbed">
      <iframe
        src="https://www.youtube-nocookie.com/embed/${escapeAttribute(video.video_id)}"
        title="${escapeAttribute(video.title)}"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
        allowfullscreen>
      </iframe>
    </div>
    <dl class="facts">
      ${editableFact("City", "city", draft.city)}
      ${editableFact("County", "county", draft.county)}
      ${editableFact("State", "state", draft.state)}
      ${editableFact("Agency", "agency", draft.agency)}
      ${editableFact("Incident date", "incident_date", draft.incident_date)}
      ${fact("Published", formatDate(video.published_at))}
    </dl>
    <div class="dataSubtext">${escapeHtml(dataSubtext(video))}</div>
    <section>
      <h3>Summary</h3>
      <div class="editableSection">
        ${summaryEditor(draft)}
        ${sectionEditButton("summary", draft.editing_summary ? "Done editing summary" : "Edit summary")}
      </div>
    </section>
    <section>
      <h3>Crime Categories</h3>
      ${crimeCategoryEditor(draft)}
    </section>
    <section>
      <h3>Outcomes</h3>
      ${outcomeEditor(draft)}
    </section>
    <section>
      <h3>Charges</h3>
      <div class="editableSection">
        ${chargesEditor(draft)}
        ${sectionEditButton("charges", "Edit charges")}
      </div>
    </section>
    <div data-review-area>
      ${reviewArea(video, changed)}
    </div>
  `;
  for (const button of els.detailContent.querySelectorAll("[data-crime-value]")) {
    button.addEventListener("click", () => selectCrime(button.dataset.crimeValue));
  }
  for (const button of els.detailContent.querySelectorAll("[data-edit-field]")) {
    button.addEventListener("click", () => editField(video, button.dataset.editField));
  }
  for (const button of els.detailContent.querySelectorAll("[data-edit-section]")) {
    button.addEventListener("click", () => editSection(video, button.dataset.editSection));
  }
  for (const button of els.detailContent.querySelectorAll("[data-remove-crime]")) {
    button.addEventListener("click", () => removeCrimeCategory(video, button.dataset.removeCrime));
  }
  const crimeSelect = els.detailContent.querySelector("[data-add-crime]");
  if (crimeSelect) {
    crimeSelect.addEventListener("change", () => addCrimeCategory(video, crimeSelect.value));
  }
  const chargesText = els.detailContent.querySelector("[data-edit-charges]");
  if (chargesText) {
    chargesText.addEventListener("input", () => updateChargesFromMarkdown(video, chargesText.value));
  }
  const summaryText = els.detailContent.querySelector("[data-edit-summary]");
  if (summaryText) {
    summaryText.addEventListener("input", () => updateSummary(video, summaryText.value));
  }
  bindReviewControls(video);
  for (const button of els.detailContent.querySelectorAll("[data-outcome-field]")) {
    button.addEventListener("click", () => toggleOutcome(video, button.dataset.outcomeField));
  }
  for (const button of els.detailContent.querySelectorAll("[data-remove-outcome]")) {
    button.addEventListener("click", () => removeOutcome(video, button.dataset.removeOutcome));
  }
  const outcomeSelect = els.detailContent.querySelector("[data-add-outcome]");
  if (outcomeSelect) {
    outcomeSelect.addEventListener("change", () => addOutcome(video, outcomeSelect.value));
  }
}

function fillSelect(select, label, values) {
  select.replaceChildren(new Option(label, ""));
  for (const value of values) select.append(new Option(displayLabel(value), value));
}

function getDraft(video) {
  if (!editDraft || editDraft.video_id !== video.video_id) {
    editDraft = {
      video_id: video.video_id,
      city: video.city || "",
      county: video.county || "",
      state: video.state || "",
      agency: video.agency || "",
      incident_date: video.incident_date || "",
      summary: video.summary || "",
      crime_categories: dedupeLabels(video.crime_categories || []),
      outcome: { ...defaultOutcome(), ..._plainObject(video.outcome) },
      charges: normalizeCharges(video),
      charges_markdown: chargesMarkdown(normalizeCharges(video)),
      editing_summary: false,
      editing_crime_categories: false,
      editing_outcomes: false,
      editing_charges: false,
      review_comment: "",
    };
  }
  return editDraft;
}

function editableFact(label, field, value) {
  return `
    <div class="editableFact">
      <dt>${escapeHtml(label)}</dt>
      <dd>
        <span>${escapeHtml(value || "Unknown")}</span>
        <button class="editButton" type="button" data-edit-field="${escapeAttribute(field)}" title="Edit ${escapeAttribute(label)}" aria-label="Edit ${escapeAttribute(label)}">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 20h9"></path>
            <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path>
          </svg>
        </button>
      </dd>
    </div>
  `;
}

function sectionEditButton(field, label) {
  return `
    <button class="editButton sectionEditButton" type="button" data-edit-section="${escapeAttribute(field)}" title="${escapeAttribute(label)}" aria-label="${escapeAttribute(label)}">
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 20h9"></path>
        <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path>
      </svg>
    </button>
  `;
}

function editField(video, field) {
  const draft = getDraft(video);
  const labels = {
    city: "City",
    county: "County",
    state: "State",
    agency: "Agency",
    incident_date: "Incident date",
  };
  const nextValue = window.prompt(`Edit ${labels[field] || field}`, draft[field] || "");
  if (nextValue === null) return;
  draft[field] = nextValue.trim();
  renderDetail(video);
}

function editSection(video, section) {
  const draft = getDraft(video);
  if (section === "crime_categories") {
    draft.editing_crime_categories = !draft.editing_crime_categories;
  }
  if (section === "outcomes") {
    draft.editing_outcomes = !draft.editing_outcomes;
  }
  if (section === "charges") {
    draft.editing_charges = !draft.editing_charges;
  }
  if (section === "summary") {
    draft.editing_summary = !draft.editing_summary;
  }
  renderDetail(video);
}

function addCrimeCategory(video, value) {
  if (!value) return;
  const draft = getDraft(video);
  draft.crime_categories = dedupeLabels([...draft.crime_categories, value]);
  renderDetail(video);
}

function removeCrimeCategory(video, value) {
  const draft = getDraft(video);
  const removeKey = displayLabel(value).toLowerCase();
  draft.crime_categories = draft.crime_categories.filter(category => displayLabel(category).toLowerCase() !== removeKey);
  renderDetail(video);
}

function updateChargesFromMarkdown(video, value) {
  const draft = getDraft(video);
  draft.charges_markdown = value;
  draft.charges = parseMarkdownList(value);
  updateReviewArea(video);
}

function updateSummary(video, value) {
  getDraft(video).summary = value;
  updateReviewArea(video);
}

function updateReviewArea(video) {
  const area = els.detailContent.querySelector("[data-review-area]");
  if (!area) return;
  area.innerHTML = reviewArea(video, draftChanged(video));
  bindReviewControls(video);
}

function bindReviewControls(video) {
  const commentText = els.detailContent.querySelector("[data-review-comment]");
  if (commentText) {
    commentText.addEventListener("input", () => {
      getDraft(video).review_comment = commentText.value;
    });
  }
  for (const button of els.detailContent.querySelectorAll("[data-review-intent]")) {
    button.addEventListener("click", () => openReviewIssue(video, button.dataset.reviewIntent));
  }
}

function toggleOutcome(video, field) {
  const draft = getDraft(video);
  draft.outcome[field] = draft.outcome[field] === true ? false : true;
  renderDetail(video);
}

function addOutcome(video, value) {
  if (!value) return;
  const draft = getDraft(video);
  draft.outcome[value] = true;
  renderDetail(video);
}

function removeOutcome(video, value) {
  const draft = getDraft(video);
  draft.outcome[value] = false;
  renderDetail(video);
}

function draftChanged(video) {
  const draft = getDraft(video);
  return (
    normalizeText(draft.city) !== normalizeText(video.city) ||
    normalizeText(draft.county) !== normalizeText(video.county) ||
    normalizeText(draft.state) !== normalizeText(video.state) ||
    normalizeText(draft.agency) !== normalizeText(video.agency) ||
    normalizeText(draft.incident_date) !== normalizeText(video.incident_date) ||
    normalizeText(draft.summary) !== normalizeText(video.summary) ||
    listChanged(draft.crime_categories, video.crime_categories || []) ||
    outcomeChanged(draft.outcome, video.outcome || {}) ||
    normalizeText(draft.charges_markdown) !== normalizeText(chargesMarkdown(normalizeCharges(video)))
  );
}

function buildReviewPatch(video, intent) {
  const draft = getDraft(video);
  const changes = changedReviewFields(video, draft, intent);
  return {
    schema_version: 1,
    kind: "metadata_review",
    intent,
    video_id: video.video_id,
    data_path: video.data_path,
    site: {
      url: window.location.href,
      submitted_at: new Date().toISOString(),
      commit: document.querySelector('meta[name="badge-video-commit"]')?.content || null,
    },
    review_comment: emptyToNull(draft.review_comment),
    changes,
  };
}

function changedReviewFields(video, draft, intent) {
  const changes = {};
  addChangedText(changes, "classification.result.incident.location.city", draft.city, video.city);
  addChangedText(changes, "classification.result.incident.location.county", draft.county, video.county);
  addChangedText(changes, "classification.result.incident.location.state", draft.state, video.state);
  addChangedText(changes, "classification.result.incident.agency.name", draft.agency, video.agency);
  addChangedText(changes, "classification.result.incident.incident_date", draft.incident_date, video.incident_date);
  addChangedText(changes, "classification.result.event_summary.short", draft.summary, video.summary);
  if (listChanged(draft.crime_categories, video.crime_categories || [])) {
    changes["classification.result.classifications.crime_categories"] = draft.crime_categories;
  }
  if (normalizeText(draft.charges_markdown) !== normalizeText(chargesMarkdown(normalizeCharges(video)))) {
    changes["classification.result.legal.charges"] = draft.charges;
    changes["classification.result.legal.alleged_crimes"] = draft.charges.map(charge => ({
      label: charge,
      category: null,
      statute: null,
      confidence: "human",
    }));
  }
  for (const [key, value] of Object.entries(draft.outcome)) {
    if (normalizeOutcome(video.outcome || {})[key] !== value) {
      changes[`classification.result.event_summary.outcome.${key}`] = value;
    }
  }
  if (intent === "approve" && video.human_reviewed !== true) {
    changes.human_reviewed = true;
  }
  if (intent === "disapprove" && video.human_reviewed !== false) {
    changes.human_reviewed = false;
  }
  return changes;
}

function addChangedText(changes, field, nextValue, currentValue) {
  if (normalizeText(nextValue) !== normalizeText(currentValue)) {
    changes[field] = emptyToNull(nextValue);
  }
}

function openReviewIssue(video, intent) {
  const draft = getDraft(video);
  if (intent === "disapprove") {
    window.alert("Please enter what you think is incorrect before submitting a disapproval request.");
    const note = window.prompt("What information looks incorrect?", draft.review_comment || "");
    if (note === null) return;
    draft.review_comment = note.trim();
  }
  window.open(buildReviewIssueUrl(video, intent), "_blank", "noopener,noreferrer");
}

function buildReviewIssueUrl(video, intent) {
  const patch = buildReviewPatch(video, intent);
  const title = `${reviewTitlePrefix(intent)} ${video.title || video.video_id}`;
  const repoPath = dataPathForGithub(video.data_path);
  const fileUrl = `https://github.com/zoogies/badge.video/blob/main/${encodePathForUrl(repoPath)}`;
  const reviewComment = patch.review_comment;
  const body = [
    "### Video metadata review",
    "",
    `- Video ID: \`${video.video_id}\``,
    `- Data file: [${repoPath}](${fileUrl})`,
    `- URL: ${video.url}`,
    reviewComment ? `- Reviewer comment: ${reviewComment}` : null,
    reviewComment ? "" : null,
    reviewComment ? `### ${reviewReasonHeading(intent)}` : null,
    reviewComment ? "" : null,
    reviewComment ? reviewComment : null,
    "",
    "### Requested JSON update",
    "",
    "```json",
    JSON.stringify(patch, null, 2),
    "```",
  ].filter(line => line !== null).join("\n");
  return `https://github.com/zoogies/badge.video/issues/new?${new URLSearchParams({
    title,
    labels: reviewIssueLabel(intent),
    body,
  }).toString()}`;
}

function dataPathForGithub(path) {
  const clean = String(path || "").replaceAll("\\", "/").replace(/^\/+/, "");
  return clean.startsWith("database/") ? clean : `database/${clean}`;
}

function encodePathForUrl(path) {
  return String(path || "")
    .split("/")
    .map(part => encodeURIComponent(part))
    .join("/");
}

function reviewIssueLabel(intent) {
  if (intent === "approve") return "requesting approval";
  if (intent === "disapprove") return "requesting disapproval";
  return "requesting changes";
}

function reviewTitlePrefix(intent) {
  if (intent === "approve") return "[Approve]";
  if (intent === "disapprove") return "[Disapprove]";
  return "[Edit]";
}

function reviewReasonHeading(intent) {
  if (intent === "disapprove") return "Disapproval reason";
  if (intent === "approve") return "Approval note";
  return "Review justification";
}

function emptyToNull(value) {
  const text = String(value || "").trim();
  return text ? text : null;
}

function normalizeText(value) {
  return String(value || "").trim();
}

function listChanged(left = [], right = []) {
  return JSON.stringify(dedupeLabels(left)) !== JSON.stringify(dedupeLabels(right));
}

function outcomeChanged(left = {}, right = {}) {
  return JSON.stringify(normalizeOutcome(left)) !== JSON.stringify(normalizeOutcome(right));
}

function normalizeOutcome(value = {}) {
  const outcome = { ...defaultOutcome(), ..._plainObject(value) };
  return Object.fromEntries(Object.keys(defaultOutcome()).map(key => [key, outcome[key] === true]));
}

function defaultOutcome() {
  return {
    arrest_made: false,
    injuries_reported: false,
    shots_fired: false,
    fatality: false,
    use_of_force: false,
    vehicle_pursuit: false,
    foot_pursuit: false,
  };
}

function _plainObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function splitEditableList(value) {
  return dedupeLabels(String(value || "").split(/[\n,]+/));
}

function fillCountyFilter() {
  const current = els.countyFilter.value;
  const selectedState = els.stateFilter.value;
  const counties = uniqueValues(allVideos
    .filter(video => !selectedState || stateNameFromVideo(video) === selectedState)
    .map(video => video.county)
    .filter(Boolean));
  els.countyFilter.replaceChildren(new Option("All counties", ""));
  for (const county of counties) {
    els.countyFilter.append(new Option(county, normalizeCounty(county)));
  }
  if ([...els.countyFilter.options].some(option => option.value === current)) {
    els.countyFilter.value = current;
  }
}

function uniqueValues(values) {
  return dedupeLabels(values).sort((a, b) => displayLabel(a).localeCompare(displayLabel(b)));
}

function stateAbbrFromFeature(feature) {
  return STATE_FIPS[feature.properties.STATE]?.[0] || null;
}

function stateNameFromFeature(feature) {
  return STATE_FIPS[feature.properties.STATE]?.[1] || "Unknown";
}

function stateAbbrFromStateFeature(feature) {
  return STATE_FIPS[feature.id]?.[0] || STATE_NAME_TO_ABBR[String(feature.properties.name || "").toLowerCase()] || null;
}

function stateNameFromStateFeature(feature) {
  return STATE_FIPS[feature.id]?.[1] || feature.properties.name || "Unknown";
}

function stateAbbrFromVideo(video) {
  const explicit = String(video.state_abbreviation || "").trim().toUpperCase();
  if (STATE_ABBR_TO_NAME[explicit]) return explicit;
  const state = String(video.state || "").trim();
  return STATE_NAME_TO_ABBR[state.toLowerCase()] || null;
}

function stateNameFromVideo(video) {
  const abbr = stateAbbrFromVideo(video);
  return abbr ? STATE_ABBR_TO_NAME[abbr] : video.state || video.state_abbreviation || null;
}

function countyKeyFromFeature(feature) {
  const abbr = stateAbbrFromFeature(feature);
  const county = normalizeCounty(feature.properties.NAME);
  return abbr && county ? `${abbr}|${county}` : null;
}

function countyKeyFromVideo(video) {
  const abbr = stateAbbrFromVideo(video);
  const county = normalizeCounty(video.county);
  return abbr && county ? `${abbr}|${county}` : null;
}

function normalizeCounty(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/\b(county|parish|borough|municipality|census area|city and borough|city)\b/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function heatColor(intensity, hasData) {
  if (!hasData) return "rgba(4, 13, 13, 0.72)";
  const clamped = Math.max(0, Math.min(1, intensity));
  const cyan = Math.round(50 + clamped * 35);
  const green = Math.round(100 + clamped * 155);
  const alpha = 0.18 + clamped * 0.64;
  return `rgba(20, ${green}, ${cyan}, ${alpha})`;
}

function searchableText(video) {
  return [
    video.title, video.channel, video.state, video.state_abbreviation, video.county, video.city,
    video.agency, video.summary, ...(video.crime_categories || []), ...(video.incident_types || []),
    ...(video.tags || []), ...(video.charges || []),
  ].filter(Boolean).join(" ").toLowerCase();
}

function sortVideos(videos, mode) {
  if (mode === "random") return sortRandom(videos);
  return [...videos].sort((a, b) => {
    if (mode === "published_asc") return String(a.published_at || "").localeCompare(String(b.published_at || ""));
    if (mode === "state") return locationLine(a).localeCompare(locationLine(b));
    if (mode === "crime") return String((a.crime_categories || [])[0] || "").localeCompare(String((b.crime_categories || [])[0] || ""));
    if (mode === "review") return Number(a.human_reviewed) - Number(b.human_reviewed);
    return String(b.published_at || "").localeCompare(String(a.published_at || ""));
  });
}

function sortRandom(videos) {
  for (const video of videos) {
    if (!randomSortOrder.has(video.video_id)) randomSortOrder.set(video.video_id, Math.random());
  }
  return [...videos].sort((a, b) => randomSortOrder.get(a.video_id) - randomSortOrder.get(b.video_id));
}

function locationLine(video) {
  return [video.city, video.county, video.state_abbreviation || video.state].filter(Boolean).join(", ") || "Unknown location";
}

function crimeCategoryEditor(draft) {
  if (!draft.editing_crime_categories) {
    return `
      <div class="editableSection">
        <div class="chips clickableChips">${chips(draft.crime_categories, true)}</div>
        ${sectionEditButton("crime_categories", "Edit crime categories")}
      </div>
    `;
  }
  return `
    <div class="editableSection categoryEditSection">
      <div>
        <div class="chips editableChips">${editableCrimeChips(draft.crime_categories)}</div>
        <label class="inlineAddLabel">
          <span><span class="plusMark">+</span> Add category</span>
          <select data-add-crime>
            <option value="">Choose category</option>
            ${availableCrimeOptions(draft.crime_categories).map(value => `<option value="${escapeAttribute(value)}">${escapeHtml(displayLabel(value))}</option>`).join("")}
          </select>
        </label>
      </div>
      ${sectionEditButton("crime_categories", "Done editing crime categories")}
    </div>
  `;
}

function chargesEditor(draft) {
  if (!draft.editing_charges) return `<ul>${chargeItems(draft)}</ul>`;
  return `
    <textarea class="markdownEdit" data-edit-charges rows="7" spellcheck="true">${escapeHtml(draft.charges_markdown)}</textarea>
  `;
}

function outcomeEditor(draft) {
  if (!draft.editing_outcomes) {
    return `
      <div class="editableSection">
        <div class="chips">${activeOutcomeChips(draft.outcome)}</div>
        ${sectionEditButton("outcomes", "Edit outcomes")}
      </div>
    `;
  }
  return `
    <div class="editableSection categoryEditSection">
      <div>
        <div class="chips editableChips">${editableOutcomeChips(draft.outcome)}</div>
        <label class="inlineAddLabel">
          <span><span class="plusMark">+</span> Add outcome</span>
          <select data-add-outcome>
            <option value="">Choose outcome</option>
            ${availableOutcomeOptions(draft.outcome).map(value => `<option value="${escapeAttribute(value)}">${escapeHtml(displayLabel(value))}</option>`).join("")}
          </select>
        </label>
      </div>
      ${sectionEditButton("outcomes", "Done editing outcomes")}
    </div>
  `;
}

function reviewCommentField(value) {
  return `
    <label class="reviewComment">
      Please justify the changes
      <textarea data-review-comment rows="4" spellcheck="true" placeholder="Briefly explain what is incorrect or what source supports the correction.">${escapeHtml(value || "")}</textarea>
    </label>
  `;
}

function reviewArea(video, changed) {
  return `
    ${changed ? reviewCommentField(getDraft(video).review_comment) : ""}
    <div class="actions">
      ${changed ? `<button class="primaryButton" type="button" data-review-intent="correction">Submit Correction</button>` : ""}
      ${video.human_reviewed
        ? `<button class="ghostButton dangerButton" type="button" data-review-intent="disapprove">Disapprove Information</button>`
        : changed ? "" : `<button class="ghostButton" type="button" data-review-intent="approve">Approve Information</button>`}
    </div>
  `;
}

function chips(values = [], clickable = false) {
  const labels = dedupeLabels(values);
  if (!labels.length) return "<span>None listed</span>";
  if (!clickable) return labels.map(value => `<span>${escapeHtml(displayLabel(value))}</span>`).join("");
  return labels.map(value => {
    const disabled = crimeOptionExists(value) ? "" : " disabled";
    return `<button type="button" data-crime-value="${escapeAttribute(value)}"${disabled}>${escapeHtml(displayLabel(value))}</button>`;
  }).join("");
}

function editableCrimeChips(values = []) {
  const labels = dedupeLabels(values);
  if (!labels.length) return "<span>None selected</span>";
  return labels.map(value => `
    <span class="editableChip">
      ${escapeHtml(displayLabel(value))}
      <button type="button" data-remove-crime="${escapeAttribute(value)}" title="Remove ${escapeAttribute(displayLabel(value))}" aria-label="Remove ${escapeAttribute(displayLabel(value))}">x</button>
    </span>
  `).join("");
}

function availableCrimeOptions(selected = []) {
  const selectedKeys = new Set(dedupeLabels(selected).map(value => displayLabel(value).toLowerCase()));
  return [...els.crimeFilter.options]
    .map(option => option.value)
    .filter(Boolean)
    .filter(value => !selectedKeys.has(displayLabel(value).toLowerCase()));
}

function activeOutcomeChips(outcome = {}) {
  return Object.entries(normalizeOutcome(outcome))
    .filter(([, value]) => value === true)
    .map(([key]) => `<span>${escapeHtml(displayLabel(key))}</span>`)
    .join("") || "<span>None flagged</span>";
}

function editableOutcomeChips(outcome = {}) {
  const active = Object.entries(normalizeOutcome(outcome)).filter(([, value]) => value === true).map(([key]) => key);
  if (!active.length) return "<span>None selected</span>";
  return active.map(value => `
    <span class="editableChip">
      ${escapeHtml(displayLabel(value))}
      <button type="button" data-remove-outcome="${escapeAttribute(value)}" title="Remove ${escapeAttribute(displayLabel(value))}" aria-label="Remove ${escapeAttribute(displayLabel(value))}">x</button>
    </span>
  `).join("");
}

function availableOutcomeOptions(outcome = {}) {
  const normalized = normalizeOutcome(outcome);
  return Object.keys(normalized).filter(key => normalized[key] !== true);
}

function summaryEditor(draft) {
  if (!draft.editing_summary) return `<p>${escapeHtml(draft.summary || "No summary available.")}</p>`;
  return `
    <textarea class="summaryEdit" data-edit-summary rows="5" spellcheck="true" placeholder="Add a short incident summary.">${escapeHtml(draft.summary)}</textarea>
  `;
}

function chargeItems(video) {
  const charges = normalizeCharges(video);
  return charges.length
    ? charges.map(charge => `<li>${escapeHtml(charge)}</li>`).join("")
    : "<li>None listed</li>";
}

function chargesMarkdown(charges = []) {
  return dedupeLabels(charges).map(charge => `- ${charge}`).join("\n");
}

function parseMarkdownList(value) {
  return dedupeLabels(String(value || "")
    .split("\n")
    .map(line => line.replace(/^\s*[-*]\s+/, "").trim()));
}

function normalizeCharges(video) {
  const values = [];
  for (const crime of video.alleged_crimes || []) {
    if (crime && typeof crime === "object" && crime.label) values.push(crime.label);
  }
  for (const charge of video.charges || []) {
    values.push(extractChargeLabel(charge));
  }
  return dedupeLabels(values);
}

function extractChargeLabel(value) {
  if (value && typeof value === "object") return value.label || value.charge || value.name || JSON.stringify(value);
  const text = String(value || "").trim();
  const labelMatch = text.match(/['"]label['"]\s*:\s*['"]([^'"]+)['"]/);
  return labelMatch ? labelMatch[1] : text;
}

function dedupeLabels(values = []) {
  const seen = new Set();
  const result = [];
  for (const value of values || []) {
    const text = String(value || "").trim();
    if (!text) continue;
    const key = displayLabel(text).toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(text);
  }
  return result;
}

function displayLabel(value) {
  return String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, char => char.toUpperCase());
}

function crimeOptionExists(value) {
  return [...els.crimeFilter.options].some(option => option.value === value);
}

function selectCrime(value) {
  if (!crimeOptionExists(value)) return;
  els.crimeFilter.value = value;
  render();
}

function dataSubtext(video) {
  const transcript = [video.transcript_source, video.transcript_model].filter(Boolean).join(" / ");
  const classifier = [video.classifier_backend, video.classifier_model].filter(Boolean).join(" / ");
  return [
    transcript ? `Transcript: ${transcript}` : null,
    classifier ? `Classifier: ${classifier}` : null,
    video.classification_generated_at ? `Generated: ${formatDate(video.classification_generated_at)}` : null,
  ].filter(Boolean).join(" | ");
}

function fact(label, value) {
  return value ? `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>` : "";
}

function formatDate(value) {
  return value ? new Date(value).toLocaleDateString() : "Unknown date";
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString() : "Unknown";
}

function debounce(fn, delay) {
  let timeout;
  return (...args) => {
    clearTimeout(timeout);
    timeout = setTimeout(() => fn(...args), delay);
  };
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  })[char]);
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

function escapeSelector(value) {
  if (window.CSS?.escape) return CSS.escape(String(value || ""));
  return String(value || "").replace(/["\\]/g, "\\$&");
}

for (const input of [
  els.searchInput,
  els.stateFilter,
  els.countyFilter,
  els.crimeFilter,
  els.reviewFilter,
  els.sortSelect,
  els.mapMode,
]) {
  input.addEventListener("input", render);
}

els.clearMapButton.addEventListener("click", () => {
  els.stateFilter.value = "";
  els.countyFilter.value = "";
  render();
});

els.resetViewButton.addEventListener("click", () => {
  d3.select(els.mapSvg).transition().duration(180).call(mapZoom.transform, d3.zoomIdentity);
});

els.randomButton.addEventListener("click", () => {
  const videos = getFilteredVideos();
  if (!videos.length) return;
  const randomVideo = videos[Math.floor(Math.random() * videos.length)];
  selectedVideoId = randomVideo.video_id;
  scrollSelectedIntoView = true;
  render();
});

boot().catch(error => {
  els.resultSummary.textContent = error.message;
  console.error(error);
});
