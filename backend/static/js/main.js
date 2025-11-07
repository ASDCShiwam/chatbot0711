let allLogs = [];
let filteredLogs = [];
let currentPage = 1;
let pageSize = 1;

let selectedDomain = "";
let selectedFeedback = "all";
let selectedFromDate = "";
let selectedToDate = "";




// Load logs on page load
document.addEventListener("DOMContentLoaded", () => {
  loadLogs();
  fetchWithAuth("/chatbot/collection-feedback/")
    .then(res => res.json())
    .then(data => renderAggregatedFeedbackChart(data));
  document.getElementById("from-date").addEventListener("change", filterLogsByDateRange);
  document.getElementById("to-date").addEventListener("change", filterLogsByDateRange);
  document.getElementById("feedbackFilter").addEventListener("change", e => {
    selectedFeedback = e.target.value;
    applyCombinedFilters();
  });
});

async function fetchWithAuth(url, options = {}) {
  const token = sessionStorage.getItem("access");  // Get the JWT token from sessionStorage

  if (!token) {
    console.error("No JWT token found in sessionStorage.");
    window.location.href = "/login";  // Redirect to login if no token is found
    return;
  }

  // Add the Authorization header with the Bearer token
  const headers = {
    "Authorization": `Bearer ${token}`,
    "Content-Type": "application/json",  // Optional: specify content type if needed
    ...options.headers,  // Allow additional headers to be passed
  };

  // Make the fetch request with the Authorization header
  const response = await fetch(url, {
    ...options,
    headers
  });

  if (response.status === 401) {
    // If the token is expired or invalid, handle the error
    console.error("Token expired or invalid. Redirecting to login.");
    window.location.href = "/login";  // Redirect to login page
    return;
  }

  return response;
}


async function loadLogs() {
  try {
    // Retrieve the token from sessionStorage
    const token = sessionStorage.getItem("access");

    if (!token) {
      console.error("No JWT token found in sessionStorage");
      // alert("You are not logged in. Please log in first.");
      window.location.href = "/login"; // Redirect to login page if no token is found
      return;  // Exit if there's no token
    }

    // Set the Authorization header with the Bearer token
    const res = await fetch("/chatbot/query-logs/", {
      method: "GET",
      headers: {
        "Authorization": `Bearer ${token}`,  // Attach the token as Bearer token
        "Content-Type": "application/json",  // Optional: set content-type if necessary
      }
    });

    if (res.status === 401) {
      // If the token is expired or invalid
      console.error("Token expired or invalid. Please log in again.");
      // alert("Session expired or unauthorized. Please log in again.");
      // Redirect the user to the login page
      window.location.href = "/login"; // Adjust URL as per your application's login page
      return;
    }

    // Proceed if the response is successful
    const data = await res.json();

    // Check if the response data contains logs
    allLogs = data.logs || [];
    filteredLogs = [...allLogs];

    populateDomainDropdown(allLogs);
    applyCombinedFilters();
    populateCollectionDropdown(allLogs); // fill dropdown

    // renderFeedbackColumnChart(allLogs); // Uncomment if needed
    renderYearlyQueryBreakup(allLogs); // This should be called inside loadLogs

  } catch (err) {
    console.error("Error loading logs:", err);
  }
}


function populateDomainDropdown(logs) {
  const select = document.getElementById("domainSelect");
  select.innerHTML = `<option value="">All Domains</option>`;

  const domains = [...new Set(logs.map(log => log.domain).filter(Boolean))];

  domains.forEach(domain => {
    const option = document.createElement("option");
    option.value = domain;
    option.textContent = domain;
    select.appendChild(option);
  });

  select.addEventListener("change", function () {
    selectedDomain = this.value;
    applyCombinedFilters();
  });
}

function populateCollectionDropdown(logs) {
  const select = document.getElementById("collectionSelect");
  const collections = [...new Set(logs.map(log => log.collection_name).filter(Boolean))];

  // Clear existing options except "All Collection"
  select.innerHTML = '<option value="">All Collection</option>';

  collections.forEach(col => {
    const option = document.createElement("option");
    option.value = col;
    option.textContent = col;
    select.appendChild(option);
  });
}

// let filteredLogs = allLogs; // your original logs array
// let currentPage = 1;
// let pageSize = 10;

document.getElementById("collectionSelect").addEventListener("change", function () {
  const selected = this.value;
  filteredLogs = selected
    ? allLogs.filter(log => log.collection_name === selected)
    : allLogs; // show all if empty
  currentPage = 1;       // reset to first page
  renderPaginatedLogs(); // your existing function
});

function applyCombinedFilters() {
  filteredLogs = allLogs.filter(log => {
    const domainMatch = !selectedDomain || log.domain === selectedDomain;
    const feedbackMatch = selectedFeedback === "all" || log.feedback === selectedFeedback;

    const logDate = new Date(log.timestamp);
    const from = selectedFromDate ? new Date(selectedFromDate) : null;
    const to = selectedToDate ? new Date(selectedToDate) : null;
    const dateMatch = (!from || logDate >= from) && (!to || logDate <= to);

    return domainMatch && feedbackMatch && dateMatch;
  });

  currentPage = 1;
  renderPaginatedLogs();
}

function filterLogsByDateRange() {
  selectedFromDate = document.getElementById("from-date").value;
  selectedToDate = document.getElementById("to-date").value;
  applyCombinedFilters();
}

function changePageSize() {
  pageSize = parseInt(document.getElementById("pageSize").value);
  currentPage = 1;
  renderPaginatedLogs();
}

function renderPaginatedLogs() {
  const start = (currentPage - 1) * pageSize;
  const end = start + pageSize;
  const currentLogs = filteredLogs.slice(start, end);
  renderLogs(currentLogs);
  renderPaginationControls();
}

function renderLogs(logs) {
  const tableBody = document.getElementById("log-table-body");
  tableBody.innerHTML = "";

  if (logs.length === 0) {
    const noDataRow = document.createElement("tr");
    noDataRow.innerHTML = `<td colspan="5" class="text-center text-muted">No logs available</td>`;
    tableBody.appendChild(noDataRow);
    return;
  }

  logs.forEach((log, index) => {
    const row = document.createElement("tr");

    // Determine checkbox checked state
    const isChecked = log.is_complete === true ? "checked" : "";

    row.innerHTML = `
    <td><input type="checkbox" class="log-checkbox" data-id="${log.id}"></td>
    <td>${index + 1}</td>
    <td>${log.collection_name || "No Collection_name"}</td>
    <td class="cell-question">${log.question || "No question"}</td>
    <td class="cell-answer">${log.answer || "No answer"}</td>
    <td>${log.feedback || "-"}</td>
    <td>${log.timestamp || "No timestamp"}</td>

    <td>
      <input 
        type="checkbox" 
        class="log-checkboxcollection"
        data-id="${log.id}" 
        data-collection="${log.collection_name || ''}"
        data-question="${(log.question || '').replace(/"/g, '&quot;')}" 
        data-answer="${(log.answer || '').replace(/"/g, '&quot;')}"
        ${isChecked}
      >
    </td>

    <td class="actions">
      <button 
        type="button" 
        class="text-sm text-white bg-red-600 hover:bg-red-700 px-3 py-1 rounded btn-delete" 
        data-id="${log.id}" 
        title="Delete"
      >
        Delete
      </button>
    </td>
  `;

    tableBody.appendChild(row);
  });

  tableBody.addEventListener("click", (e) => {
    if (e.target.classList.contains("btn-delete")) {
      const id = e.target.dataset.id;
      deleteLog(id, e.target);
    }
  });
}


// Function to delete a log row by ID
async function deleteLog(id, buttonElement) {
  if (!id) return;

  // Confirmation before deleting
  if (!confirm("Are you sure you want to delete this log?")) return;

  // Disable the button while deleting
  buttonElement.disabled = true;
  const originalText = buttonElement.textContent;
  buttonElement.textContent = "Deleting...";

  try {
    // 👇 Replace this URL with your actual delete API endpoint
    const response = await fetch(`/chatbot/logs/${id}/`, {
      method: "DELETE",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (response.ok) {
      // Remove the row from the table
      const row = buttonElement.closest("tr");
      if (row) {
        row.remove();
        updateSerialNumbers(); // Recalculate serial numbers
      }
    } else {
      const data = await response.json();
      alert(data.message || "Failed to delete the log");
    }
  } catch (error) {
    console.error("Error deleting log:", error);
    alert("An error occurred while deleting the log");
  } finally {
    // Re-enable the button
    buttonElement.disabled = false;
    buttonElement.textContent = originalText;
  }
}

// Function to update serial numbers after a deletion
function updateSerialNumbers() {
  const rows = document.querySelectorAll("#tableBody tr");
  rows.forEach((row, index) => {
    const snoCell = row.querySelector(".sno");
    if (snoCell) snoCell.textContent = index + 1;
  });
}
function renderPaginationControls() {
  const container = document.getElementById("pagination-controls");
  container.innerHTML = ""; // Clear previous buttons

  const totalItems = filteredLogs.length;
  const totalPages = Math.ceil(totalItems / pageSize);
  if (totalPages <= 1) return; // No pagination needed

  // Previous button
  const prevBtn = document.createElement("button");
  prevBtn.className = "btn btn-sm btn-primary";
  prevBtn.textContent = "Prev";
  prevBtn.disabled = currentPage === 1;
  prevBtn.onclick = () => {
    currentPage--;
    renderPaginatedLogs();
  };
  container.appendChild(prevBtn);

  // Page numbers (limit to 5 at a time)
  let startPage = Math.max(1, currentPage - 2);
  let endPage = Math.min(totalPages, currentPage + 2);

  if (endPage - startPage < 4) {
    // Adjust the range if less than 5 pages are available
    startPage = Math.max(1, endPage - 4);
  }

  for (let i = startPage; i <= endPage; i++) {
    const pageBtn = document.createElement("button");
    pageBtn.className = `btn btn-sm ${i === currentPage ? "btn-primary" : "btn-outline-primary"}`;
    pageBtn.textContent = i;
    pageBtn.onclick = () => {
      currentPage = i;
      renderPaginatedLogs();
    };
    container.appendChild(pageBtn);
  }

  // Next button
  const nextBtn = document.createElement("button");
  nextBtn.className = "btn btn-sm btn-primary";
  nextBtn.textContent = "Next";
  nextBtn.disabled = currentPage === totalPages;
  nextBtn.onclick = () => {
    currentPage++;
    renderPaginatedLogs();
  };
  container.appendChild(nextBtn);
}


// Example usage: call this after filtering or changing page size
renderPaginatedLogs();


function toggleSelectAll() {
  const selectAllCheckbox = document.getElementById("select-all");
  const checkboxes = document.querySelectorAll(".log-checkbox");
  checkboxes.forEach(cb => cb.checked = selectAllCheckbox.checked);
}

function getSelectedLogs() {
  const selected = [];
  document.querySelectorAll(".log-checkbox:checked").forEach(cb => {
    const id = cb.dataset.id;
    const log = allLogs.find(log => log.id == id);
    if (log) selected.push(log);
  });
  return selected;
}

function exportToCSV() {
  const selectedLogs = getSelectedLogs();
  const logsToExport = selectedLogs.length ? selectedLogs : filteredLogs;

  if (!logsToExport.length) {
    alert("No logs to export.");
    return;
  }

  const headers = ["Question", "Answer", "Feedback", "Timestamp"];
  const rows = logsToExport.map(log => [
    `"${log.question?.replace(/"/g, '""') || ''}"`,
    `"${log.answer?.replace(/"/g, '""') || ''}"`,
    `"${log.feedback || '-'}"`,
    `"${log.timestamp || '-'}"`
  ]);

  const csvContent = [headers.join(","), ...rows.map(r => r.join(","))].join("\n");

  const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "logs_export.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function resetAllFilters() {
  selectedDomain = "";
  selectedFeedback = "all";
  selectedFromDate = "";
  selectedToDate = "";

  document.getElementById("domainSelect").value = "";
  document.getElementById("feedbackFilter").value = "all";
  document.getElementById("from-date").value = "";
  document.getElementById("to-date").value = "";
  document.getElementById("pageSize").value = "50";
  document.getElementById("select-all").checked = false;

  pageSize = 50;
  applyCombinedFilters();
}
function resetAllFilters() {
  selectedDomain = "";
  selectedFeedback = "all";
  selectedFromDate = "";
  selectedToDate = "";

  document.getElementById("domainSelect").value = "";
  document.getElementById("feedbackFilter").value = "all";
  document.getElementById("from-date").value = "";
  document.getElementById("to-date").value = "";
  document.getElementById("pageSize").value = "50";
  document.getElementById("select-all").checked = false;

  pageSize = 50;
  applyCombinedFilters();
}
function filterLogsByFeedback() {
  const feedbackSelect = document.getElementById("feedbackFilter");
  selectedFeedback = feedbackSelect ? feedbackSelect.value : "all";
  applyCombinedFilters();
}
function renderAggregatedFeedbackChart(apiData) {
  // console.log("Rendering aggregated feedback chart with data:", apiData);
  const collectionFeedback = apiData.collection_feedback;

  // Extract collections and feedback types dynamically
  const collections = Object.keys(collectionFeedback);
  const feedbackTypesSet = new Set();
  collections.forEach(col => {
    Object.keys(collectionFeedback[col]).forEach(fb => feedbackTypesSet.add(fb));
  });
  const feedbackTypes = Array.from(feedbackTypesSet);

  // Prepare series data
  const series = feedbackTypes.map(fb => ({
    name: fb === "null" ? "No Feedback" : fb.charAt(0).toUpperCase() + fb.slice(1),
    data: collections.map(col => collectionFeedback[col][fb] || 0)
  }));

  const options = {
    chart: {
      type: 'bar',
      height: 400,
      width: '100%',
      stacked: false
    },
    plotOptions: {
      bar: {
        horizontal: false,
        columnWidth: '60%',
        endingShape: 'rounded',
        dataLabels: {
          position: 'top'   // ✅ move labels on top of the bar
        }
      }
    },
    dataLabels: {
      enabled: true,
      style: {
        colors: ['#000']   // ✅ black color
      },
      offsetY: -20,        // ✅ move labels further above bar
      formatter: function (val) {
        return val;        // show raw number; you can format if needed
      }
    },
    series: series,
    xaxis: {
      categories: collections
    },
    colors: ['#f51313ff', '#4CAF50', '#ffe600ff'],
    legend: { position: 'top' },
    fill: { opacity: 1 }
  };


  if (window.feedbackChart) window.feedbackChart.destroy();
  window.feedbackChart = new ApexCharts(document.querySelector("#chart-bar"), options);
  window.feedbackChart.render();
}
function renderYearlyQueryBreakup(logs) {
  const total = logs.length;
  const likeCount = logs.filter(log => log.feedback === "like").length;
  const dislikeCount = logs.filter(log => log.feedback === "dislike").length;
  const neutralCount = total - (likeCount + dislikeCount);

  const breakupEl = document.querySelector("#breakup");
  if (!breakupEl) return;

  // Update summary text
  document.getElementById("totalQueryCount").textContent = `${total} Queries`;
  document.getElementById("percentageFeedback").textContent = `${total > 0 ? Math.round(((likeCount + dislikeCount) / total) * 100) : 0}% Feedback`;

  // Clear previous chart
  breakupEl.innerHTML = "";

  const options = {
    series: [likeCount, dislikeCount, neutralCount],
    chart: {
      type: 'donut',
      height: 250
    },
    labels: ['Like', 'Dislike', 'No Feedback'],
    colors: ['#4CAF50', '#FF5252', '#fde82dff'],
    dataLabels: {
      enabled: true,
      formatter: (val, opts) => {
        const label = opts.w.globals.labels[opts.seriesIndex];
        // return `${label}: ${val} (${Math.round((val / total) * 100)}%)`;
      }
    },
    legend: {
      position: 'bottom'
    }
  };

  const chart = new ApexCharts(breakupEl, options);
  chart.render();
}



function renderPdfChart(growthPercent) {
  const chartDiv = document.querySelector("#earning");
  if (!chartDiv) {
    console.error("Element #earning not found");
    return;
  }

  const options = {
    chart: {
      height: 120,  // increase from 20 for visibility
      type: 'radialBar',
      toolbar: { show: false },
      sparkline: { enabled: true }  // if you want compact style
    },
    series: [growthPercent],
    labels: ["Monthly Upload Growth"],
    plotOptions: {
      radialBar: {
        hollow: {
          size: '60%'
        },
        dataLabels: {
          show: true,
          name: {
            show: false
          },
          value: {
            fontSize: '18px',
            fontWeight: 600,
            formatter: function (val) {
              return `${val}%`;
            }
          }
        }
      }
    },
    colors: ['#5D87FF']
  };

  if (window.pdfChart) window.pdfChart.destroy();

  window.pdfChart = new ApexCharts(chartDiv, options);
  window.pdfChart.render();
}
function updatePdfStats() {
  const accessToken = sessionStorage.getItem('access');  // Retrieve the access token from sessionStorage

  if (!accessToken) {
    // alert("You are not logged in. Please log in first.");
    // window.location.href = '/login';  // Redirect to login if no access token is found
    return;
  }

  // Include the access token in the Authorization header
  const headers = {
    'Authorization': `Bearer ${accessToken}`,
  };

  fetch('/chatbot/store-pdf/', { headers })
    .then(res => {
      if (res.status === 401 || res.status === 403) {
        // If status code is 401 or 403 (Unauthorized or Forbidden), alert and stop further processing
        alert("Session expired or unauthorized. Please log in againqqq.");
        // window.location.href = '/login';  // Redirect to login page
        return;  // Stop further processing
      }
      return res.json();  // Process the response as JSON if status is not 401 or 403
    })
    .then(data => {
      if (!data) return;  // If no data is returned, stop further execution

      const totalPDFs = data.length;
      document.getElementById("pdfCount").textContent = `${totalPDFs}`;

      const currentMonth = new Date().getMonth();
      const uploadsThisMonth = data.filter(pdf => {
        const uploadedMonth = new Date(pdf.created_at).getMonth();
        return uploadedMonth === currentMonth;
      });

      const growth = totalPDFs > 0
        ? Math.round((uploadsThisMonth.length / totalPDFs) * 100)
        : 0;

      document.getElementById("pdfGrowth").textContent = `+${growth}%`;

      // renderPdfChart(growth);
    })
    .catch(err => {
      console.error("Failed to fetch PDF data:", err);
      document.getElementById("pdfCount").textContent = "Error";
      document.getElementById("pdfGrowth").textContent = "";
    });
}

document.addEventListener("DOMContentLoaded", () => {
  // console.log("DOM fully loaded, calling updatePdfStats");
  updatePdfStats();
});
const editModal = document.getElementById("editModal");
const editQuestion = document.getElementById("editQuestion");
const editAnswer = document.getElementById("editAnswer");
const saveEditBtn = document.getElementById("saveEdit");
const closeEditBtn = document.getElementById("closeEditModal");

let currentRow = null;
let currentId = null;

// ---------- Utility ----------
function openModal() {
  editModal.classList.remove("hidden");
}
function closeModal() {
  editModal.classList.add("hidden");
  if (currentRow) {
    const cb = currentRow.querySelector(".log-checkboxcollection");
    if (cb) cb.checked = false;
  }
  currentRow = null;
  currentId = null;
}
function makeQAString(q, a) {
  const clean = s => String(s ?? "").replace(/^["']+|["']+$/g, "").trim();
  const qClean = clean(q);
  const aClean = clean(a);
  const qLine = qClean.startsWith("Q:") ? qClean : `Q: ${qClean || "N/A"}`;
  const aLine = aClean.startsWith("A:") ? aClean : `A: ${aClean || "N/A"}`;
  return `${qLine}\n${aLine}`;
}

// ---------- Open modal on checkbox ----------
document.addEventListener("change", (e) => {
  if (!e.target.matches(".log-checkboxcollection")) return;

  if (e.target.checked) {
    currentRow = e.target.closest("tr");
    currentId = e.target.dataset.id;

    const q = e.target.dataset.question ||
      currentRow.querySelector(".cell-question")?.textContent || "";
    const a = e.target.dataset.answer ||
      currentRow.querySelector(".cell-answer")?.textContent || "";

    editQuestion.value = q === "No question" ? "" : q;
    editAnswer.value = a === "No answer" ? "" : a;

    openModal();
  }
});

// ---------- Close modal ----------
closeEditBtn.addEventListener("click", closeModal);
editModal.addEventListener("click", (e) => {
  if (e.target === editModal) closeModal();
});

saveEditBtn.addEventListener("click", async () => {
  if (!currentId || !currentRow) return;

  const updatedQuestion = editQuestion.value.trim();
  const updatedAnswer = editAnswer.value.trim();

  // get checkbox + dataset values
  const cb = currentRow.querySelector(".log-checkboxcollection");
  const collName = cb?.dataset.collection || "";
  const logId = cb?.dataset.id; // <— use this id for mark-complete
  const collSlug = `chatbot_${collName}`;
  console.log("Collection slug:", collSlug, collName, "Log ID:", logId);

  const url = `/chatbot/add-chunk/`;
  const body = {
    collection_name: collName,
    text: makeQAString(updatedQuestion, updatedAnswer),
  };

  try {
    // 1️⃣ Send the add-chunk request
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });

    if (!res.ok) {
      const err = await res.text();
      throw new Error(err || "Failed to add chunk");
    }

    // 2️⃣ If successful, immediately call mark-complete using the same ID
    if (logId) {
      const markUrl = `/chatbot/mark-complete/${encodeURIComponent(logId)}/`;
      const markRes = await fetch(markUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({})
      });

      if (!markRes.ok) {
        const err = await markRes.text();
        throw new Error(err || "Failed to mark as complete");
      }
      // console.log("✅ Marked complete for log ID:", logId);
      alert("Successfully added chunk and marked log as complete.");
      window.location.reload();
    }

    // 3️⃣ Update UI instantly
    const qCell = currentRow.querySelector(".cell-question") || currentRow.cells?.[3];
    const aCell = currentRow.querySelector(".cell-answer") || currentRow.cells?.[4];
    if (qCell) qCell.textContent = updatedQuestion || "No question";
    if (aCell) aCell.textContent = updatedAnswer || "No answer";

    // sync data attributes
    if (cb) {
      cb.dataset.question = updatedQuestion;
      cb.dataset.answer = updatedAnswer;
      cb.checked = false;
    }

    closeModal();
  } catch (err) {
    console.error(err);
    alert(`Error updating log: ${err.message}`);
  }
});
