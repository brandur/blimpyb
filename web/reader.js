"use strict";
// All search data is embedded in the index; file:// and offline use both work.
const list = document.querySelector("#articles");
if (list) {
  const search = document.querySelector("#search");
  const year = document.querySelector("#year");
  const category = document.querySelector("#category");
  const sort = document.querySelector("#sort");
  const rows = [...list.children];
  const params = new URLSearchParams(location.search);
  search.value = params.get("q") || "";
  year.value = params.get("year") || "";
  category.value = params.get("category") || "";
  sort.value = params.get("sort") === "oldest" ? "oldest" : "newest";
  function filter(updateURL = true) {
    const words = search.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
    let count = 0;
    rows.sort((a, b) => sort.value === "oldest"
      ? a.dataset.date.localeCompare(b.dataset.date)
      : b.dataset.date.localeCompare(a.dataset.date));
    for (const row of rows) {
      row.hidden = !(words.every(word => row.dataset.search.includes(word))
        && (!year.value || row.dataset.year === year.value)
        && (!category.value || JSON.parse(row.dataset.categories).includes(category.value)));
      if (!row.hidden) count++;
      list.append(row);
    }
    document.querySelector("#result-count").textContent = `${count} article${count === 1 ? "" : "s"}`;
    document.querySelector("#empty").hidden = count > 0;
    if (updateURL && location.protocol !== "file:") {
      const query = new URLSearchParams();
      if (search.value) query.set("q", search.value);
      if (year.value) query.set("year", year.value);
      if (category.value) query.set("category", category.value);
      if (sort.value === "oldest") query.set("sort", "oldest");
      history.replaceState(null, "", location.pathname + (query.size ? "?" + query : ""));
    }
  }
  for (const control of [search, year, category, sort]) control.addEventListener("input", () => filter());
  filter(false);
}

const showGaps = document.querySelector("#show-gaps");
if (showGaps) {
  showGaps.addEventListener("change", () => {
    for (const figure of document.querySelectorAll(".gallery-grid figure")) {
      if (figure.querySelector(".missing-photo")) figure.hidden = !showGaps.checked;
    }
  });
}
