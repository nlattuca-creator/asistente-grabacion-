const beatForm = document.getElementById("beat-form");
const bStatus = document.getElementById("b-status");
const bPlayer = document.getElementById("b-result-player");
const bDownloadLink = document.getElementById("b-result-download");
const bSubmitBtn = document.getElementById("b-submit-btn");
const bDetectBtn = document.getElementById("b-detect-bpm-btn");
const bBpmReferenceInput = document.getElementById("b-bpm-reference");
const bDetectStatus = document.getElementById("b-detect-bpm-status");

bDetectBtn.addEventListener("click", () => {
  bBpmReferenceInput.click();
});

bBpmReferenceInput.addEventListener("change", async () => {
  const file = bBpmReferenceInput.files[0];
  if (!file) return;

  const apiBase = document.getElementById("api_base").value.replace(/\/$/, "");
  const body = new FormData();
  body.append("file", file);

  bDetectBtn.disabled = true;
  bDetectStatus.textContent = "Analizando…";

  try {
    const response = await fetch(`${apiBase}/api/tempo/detect`, {
      method: "POST",
      body,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Error ${response.status}`);

    document.getElementById("b-bpm").value = data.bpm;
    bDetectStatus.textContent = `Detectado: ${data.bpm} BPM (revisalo, puede fallar por octava).`;
  } catch (err) {
    bDetectStatus.textContent = `Error: ${err.message}`;
  } finally {
    bDetectBtn.disabled = false;
  }
});

beatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const apiBase = document.getElementById("api_base").value.replace(/\/$/, "");
  const body = new FormData();
  body.append("style", document.getElementById("b-style").value);
  body.append("bpm", document.getElementById("b-bpm").value);
  body.append("bars", document.getElementById("b-bars").value);

  bSubmitBtn.disabled = true;
  bStatus.textContent = "Generando patrón con IA…";
  bPlayer.hidden = true;
  bDownloadLink.hidden = true;

  try {
    const response = await fetch(`${apiBase}/api/beatmaker/generate`, {
      method: "POST",
      body,
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      throw new Error(errorBody?.detail || `Error ${response.status}`);
    }

    const blob = await response.blob();
    const zipBuffer = await blob.arrayBuffer();

    const zipUrl = URL.createObjectURL(blob);
    bDownloadLink.href = zipUrl;
    bDownloadLink.download = "bateria.zip";
    bDownloadLink.hidden = false;

    try {
      const wavBytes = extractStoredZipEntry(zipBuffer, "preview.wav");
      const wavUrl = URL.createObjectURL(new Blob([wavBytes], { type: "audio/wav" }));
      bPlayer.src = wavUrl;
      bPlayer.hidden = false;
      bStatus.textContent = "Listo. El preview es un render simple, no de estudio — el MIDI del ZIP es lo que usás en Logic con tus propios sonidos.";
    } catch (zipErr) {
      bStatus.textContent = `Listo, pero no pude armar el preview automático (${zipErr.message}). Descargá el ZIP igual.`;
    }
  } catch (err) {
    bStatus.textContent = `Error: ${err.message}`;
  } finally {
    bSubmitBtn.disabled = false;
  }
});
