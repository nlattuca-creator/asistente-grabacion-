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
