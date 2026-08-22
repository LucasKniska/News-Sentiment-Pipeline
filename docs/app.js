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
