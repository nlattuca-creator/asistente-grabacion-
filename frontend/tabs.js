const tabButtons = document.querySelectorAll(".tab-btn");
const tabPanels = document.querySelectorAll(".tab-panel");

function activateTab(tabId) {
  let matched = false;
  tabButtons.forEach((btn) => {
    const isActive = btn.dataset.tab === tabId;
    btn.classList.toggle("active", isActive);
    if (isActive) matched = true;
  });
  if (!matched) return;
  tabPanels.forEach((panel) => {
    panel.hidden = panel.dataset.tab !== tabId;
  });
  if (location.hash !== `#${tabId}`) {
    history.replaceState(null, "", `#${tabId}`);
  }
}

tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

const initialTab = location.hash.replace("#", "") || tabButtons[0]?.dataset.tab;
if (initialTab) activateTab(initialTab);

const settingsToggle = document.getElementById("settings-toggle");
const settingsPanel = document.getElementById("settings-panel");

settingsToggle.addEventListener("click", () => {
  settingsPanel.hidden = !settingsPanel.hidden;
});
