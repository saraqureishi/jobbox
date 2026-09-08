// JobBox dashboard interactivity: save toggle, status confirm, live search.

async function post(url, data) {
  const body = new URLSearchParams(data);
  const resp = await fetch(url, {
    method: "POST",
    headers: { "X-Requested-With": "fetch", "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  return resp.json();
}

document.addEventListener("click", async (e) => {
  // Save / unsave a job
  const saveBtn = e.target.closest(".save-btn");
  if (saveBtn) {
    const key = saveBtn.dataset.key;
    const currentlySaved = saveBtn.dataset.saved === "1";
    const next = currentlySaved ? 0 : 1;
    const res = await post(`/save/${key}`, { saved: next });
    if (res.ok) {
      saveBtn.dataset.saved = next ? "1" : "0";
      saveBtn.classList.toggle("saved", !!next);
      saveBtn.textContent = next ? "★" : "☆";
      // On the Saved page, remove the row when unsaving.
      if (!next && document.querySelector(".page-title")) {
        saveBtn.closest(".job-row")?.remove();
      }
    }
    return;
  }

  // Confirm / reject a detected status ("Did we read this right?")
  const decBtn = e.target.closest(".confirm-actions button");
  if (decBtn) {
    const row = decBtn.closest(".confirm-row");
    const key = row.dataset.key;
    const decision = decBtn.dataset.decision;
    const res = await post(`/status/${key}/confirm`, { decision });
    if (res.ok) {
      row.style.transition = "opacity .2s";
      row.style.opacity = "0";
      setTimeout(() => row.remove(), 200);
    }
    return;
  }
});

// Live search filter over job rows.
const search = document.getElementById("job-search");
if (search) {
  search.addEventListener("input", () => {
    const q = search.value.trim().toLowerCase();
    document.querySelectorAll(".job-row").forEach((row) => {
      const hay = row.dataset.search || "";
      row.style.display = !q || hay.includes(q) ? "" : "none";
    });
    // Hide empty date groups.
    document.querySelectorAll(".date-group").forEach((g) => {
      const anyVisible = [...g.querySelectorAll(".job-row")].some((r) => r.style.display !== "none");
      g.style.display = anyVisible ? "" : "none";
    });
  });
}
