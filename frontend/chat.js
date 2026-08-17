const chatToggle = document.getElementById("chat-toggle");
const chatPanel = document.getElementById("chat-panel");
const chatClose = document.getElementById("chat-close");
const chatMessages = document.getElementById("chat-messages");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");

const history = [];

chatToggle.addEventListener("click", () => {
  chatPanel.hidden = false;
  chatToggle.hidden = true;
  chatInput.focus();
});

chatClose.addEventListener("click", () => {
  chatPanel.hidden = true;
  chatToggle.hidden = false;
});

function appendMessage(role, content) {
  const el = document.createElement("div");
  el.className = `chat-msg chat-msg--${role}`;
  el.textContent = content;
  chatMessages.appendChild(el);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return el;
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = "";
  chatInput.disabled = true;
  history.push({ role: "user", content: text });
  appendMessage("user", text);
  const pending = appendMessage("assistant", "…");

  const apiBase = document.getElementById("api_base").value.replace(/\/$/, "");

  try {
    const response = await fetch(`${apiBase}/api/assistant/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Error ${response.status}`);

    pending.textContent = data.content;
    history.push({ role: "assistant", content: data.content });
  } catch (err) {
    pending.textContent = `Error: ${err.message}`;
    history.pop();
  } finally {
    chatInput.disabled = false;
    chatInput.focus();
  }
});
