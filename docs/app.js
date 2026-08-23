import { DatabricksDashboard } from "https://cdn.jsdelivr.net/npm/@databricks/aibi-client@1.0.3-alpha.0/+esm";

const DASHBOARD_TOKEN_URL = "https://1ghri8v2si.execute-api.us-east-1.amazonaws.com/dashboard-token";

const statusEl = document.getElementById("status");
const statusTextEl = statusEl.querySelector(".status-text");
const containerEl = document.getElementById("dashboard-container");

async function fetchEmbedConfig() {
  const response = await fetch(DASHBOARD_TOKEN_URL);
  if (!response.ok) {
    throw new Error(`dashboard-token request failed: ${response.status}`);
  }
  return response.json();
}

async function main() {
  const config = await fetchEmbedConfig();

  const dashboard = new DatabricksDashboard({
    instanceUrl: config.instanceUrl,
    workspaceId: config.workspaceId,
    dashboardId: config.dashboardId,
    token: config.token,
    container: containerEl,
    getNewToken: async () => (await fetchEmbedConfig()).token,
  });

  await dashboard.initialize();
  statusEl.hidden = true;
}

main().catch((err) => {
  console.error(err);
  statusEl.classList.add("status--error");
  statusTextEl.textContent = `Failed to load dashboard: ${err.message}`;
});

const comparisonStatusEl = document.getElementById("model-comparison-status");
const comparisonStatusTextEl = comparisonStatusEl.querySelector(".status-text");
const comparisonTableEl = document.getElementById("model-comparison-table");
const comparisonTableBodyEl = comparisonTableEl.querySelector("tbody");

function formatCost(usd) {
  return `$${usd.toFixed(4)}`;
}

async function loadModelComparison() {
  const response = await fetch("model_comparison.json");
  if (!response.ok) {
    throw new Error(`model_comparison.json request failed: ${response.status}`);
  }
  const data = await response.json();

  for (const row of data.models) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.model}</td>
      <td>${row.provider}</td>
      <td>${row.mae.toFixed(3)}</td>
      <td>${row.omitted}</td>
      <td>${row.skipAgreement}</td>
      <td>${row.failCount}</td>
      <td>${row.latencyMeanS.toFixed(2)}s</td>
      <td>${row.latencyP95S.toFixed(2)}s</td>
      <td>${formatCost(row.estCostUsd)}</td>
    `;
    comparisonTableBodyEl.appendChild(tr);
  }

  comparisonStatusEl.hidden = true;
  comparisonTableEl.hidden = false;
}

loadModelComparison().catch((err) => {
  console.error(err);
  comparisonStatusEl.classList.add("status--error");
  comparisonStatusTextEl.textContent = `Failed to load model comparison: ${err.message}`;
});
