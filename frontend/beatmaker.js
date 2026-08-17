const beatForm = document.getElementById("beat-form");
const bStatus = document.getElementById("b-status");
const bPlayer = document.getElementById("b-result-player");
const bDownloadLink = document.getElementById("b-result-download");
const bSubmitBtn = document.getElementById("b-submit-btn");
const bReferenceInput = document.getElementById("b-reference");
const bReferenceStatus = document.getElementById("b-reference-status");

bReferenceInput.addEventListener("change", async () => {
  const file = bReferenceInput.files[0];
  if (!file) {
    bReferenceStatus.textContent = "";
    return;
  }

  const apiBase = document.getElementById("api_base").value.replace(/\/$/, "");
  const body = new FormData();
  body.append("file", file);

  bReferenceStatus.textContent = "Analizando tempo…";

  try {
    const response = await fetch(`${apiBase}/api/tempo/detect`, {
      method: "POST",
      body,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Error ${response.status}`);

    document.getElementById("b-bpm").value = data.bpm;
    bReferenceStatus.textContent =
      `BPM detectado: ${data.bpm} (revisalo, puede fallar por octava). ` +
      `Al generar, también se le va a pasar a Claude la tonalidad y duración de este audio como contexto.`;
  } catch (err) {
    bReferenceStatus.textContent = `No se pudo analizar el tempo automáticamente (${err.message}), pero igual se va a usar como contexto al generar.`;
  }
});

beatForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const referenceFile = bReferenceInput.files[0];
  const bpmValue = document.getElementById("b-bpm").value;
  if (!bpmValue && !referenceFile) {
    bStatus.textContent = "Falta el BPM, o subí una canción de referencia para detectarlo.";
    return;
  }

  const apiBase = document.getElementById("api_base").value.replace(/\/$/, "");
  const body = new FormData();
  body.append("style", document.getElementById("b-style").value);
  body.append("bars", document.getElementById("b-bars").value);
  if (bpmValue) body.append("bpm", bpmValue);
  if (referenceFile) body.append("reference", referenceFile);

  bSubmitBtn.disabled = true;
  bStatus.textContent = referenceFile
    ? "Analizando la canción y generando patrón con IA…"
    : "Generando patrón con IA…";
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

    const usedBpm = response.headers.get("x-beatmaker-bpm");
    const usedKey = response.headers.get("x-beatmaker-key");

    const blob = await response.blob();
    const zipBuffer = await blob.arrayBuffer();

    const zipUrl = URL.createObjectURL(blob);
    bDownloadLink.href = zipUrl;
    bDownloadLink.download = "bateria.zip";
    bDownloadLink.hidden = false;

    let contextMsg = usedBpm ? ` (usó ${usedBpm} BPM` : "";
    if (usedKey) contextMsg += `, tonalidad estimada ${usedKey}`;
    if (contextMsg) contextMsg += ")";

    try {
      const wavBytes = extractStoredZipEntry(zipBuffer, "preview.wav");
      const wavUrl = URL.createObjectURL(new Blob([wavBytes], { type: "audio/wav" }));
      bPlayer.src = wavUrl;
      bPlayer.hidden = false;
      bStatus.textContent = `Listo${contextMsg}. El preview es un render simple, no de estudio — el MIDI del ZIP es lo que usás en Logic con tus propios sonidos.`;
    } catch (zipErr) {
      bStatus.textContent = `Listo${contextMsg}, pero no pude armar el preview automático (${zipErr.message}). Descargá el ZIP igual.`;
    }
  } catch (err) {
    bStatus.textContent = `Error: ${err.message}`;
  } finally {
    bSubmitBtn.disabled = false;
  }
});
