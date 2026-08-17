const apiBaseInput = document.getElementById("api_base");
if (!apiBaseInput.value && location.protocol === "file:") {
  apiBaseInput.value = "http://localhost:8000";
}

const form = document.getElementById("tempo-form");
const statusEl = document.getElementById("status");
const player = document.getElementById("result-player");
const downloadLink = document.getElementById("result-download");
const submitBtn = document.getElementById("submit-btn");

document.querySelectorAll('input[name="modo"]').forEach((radio) => {
  radio.addEventListener("change", () => {
    const modo = form.querySelector('input[name="modo"]:checked').value;
    document.getElementById("modo-ratio").hidden = modo !== "ratio";
    document.getElementById("modo-bpm").hidden = modo !== "bpm";
  });
});

const detectBpmBtn = document.getElementById("detect-bpm-btn");
const detectBpmStatus = document.getElementById("detect-bpm-status");

detectBpmBtn.addEventListener("click", async () => {
  const file = document.getElementById("file").files[0];
  if (!file) {
    detectBpmStatus.textContent = "Primero elegí un archivo de audio.";
    return;
  }

  const apiBase = document.getElementById("api_base").value.replace(/\/$/, "");
  const body = new FormData();
  body.append("file", file);

  detectBpmBtn.disabled = true;
  detectBpmStatus.textContent = "Analizando…";

  try {
    const response = await fetch(`${apiBase}/api/tempo/detect`, {
      method: "POST",
      body,
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Error ${response.status}`);

    document.getElementById("bpm_from").value = data.bpm;
    detectBpmStatus.textContent = `Detectado: ${data.bpm} BPM (revisalo, la detección automática puede fallar, sobre todo por octava — el doble o la mitad del BPM real).`;
  } catch (err) {
    detectBpmStatus.textContent = `Error: ${err.message}`;
  } finally {
    detectBpmBtn.disabled = false;
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const file = document.getElementById("file").files[0];
  if (!file) return;

  const modo = form.querySelector('input[name="modo"]:checked').value;
  const apiBase = document.getElementById("api_base").value.replace(/\/$/, "");
  const outputFormat = document.getElementById("output_format").value;

  const body = new FormData();
  body.append("file", file);
  body.append("output_format", outputFormat);

  if (modo === "ratio") {
    body.append("tempo_ratio", document.getElementById("tempo_ratio").value);
  } else {
    body.append("bpm_from", document.getElementById("bpm_from").value);
    body.append("bpm_to", document.getElementById("bpm_to").value);
  }

  submitBtn.disabled = true;
  statusEl.textContent = "Procesando…";
  player.hidden = true;
  downloadLink.hidden = true;

  try {
    const response = await fetch(`${apiBase}/api/tempo/process`, {
      method: "POST",
      body,
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      throw new Error(errorBody?.detail || `Error ${response.status}`);
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);

    player.src = url;
    player.hidden = false;

    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    downloadLink.href = url;
    downloadLink.download = match ? match[1] : `resultado.${outputFormat}`;
    downloadLink.hidden = false;

    statusEl.textContent = "Listo.";
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
  } finally {
    submitBtn.disabled = false;
  }
});
