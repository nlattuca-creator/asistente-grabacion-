const sessionForm = document.getElementById("session-form");
const sStatus = document.getElementById("s-status");
const sResults = document.getElementById("s-results");
const sResultDownload = document.getElementById("s-result-download");
const sSubmitBtn = document.getElementById("s-submit-btn");
const sTargetsInput = document.getElementById("s-targets");
const sTargetsStatus = document.getElementById("s-targets-status");
const sStrengthInput = document.getElementById("s-strength");
const sStrengthValue = document.getElementById("s-strength-value");

sStrengthInput.addEventListener("input", () => {
  sStrengthValue.textContent = `${sStrengthInput.value}%`;
});

sTargetsInput.addEventListener("change", () => {
  const files = Array.from(sTargetsInput.files);
  sTargetsStatus.textContent = files.length
    ? `${files.length} pista(s): ${files.map((f) => f.name).join(", ")}`
    : "";
});

sessionForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const reference = document.getElementById("s-reference").files[0];
  const targets = Array.from(sTargetsInput.files);
  if (!reference || targets.length === 0) return;

  const apiBase = document.getElementById("api_base").value.replace(/\/$/, "");
  const outputFormat = document.getElementById("s-output_format").value;

  const body = new FormData();
  body.append("reference", reference);
  targets.forEach((file) => body.append("targets", file));
  body.append("subdivision", document.getElementById("s-subdivision").value);
  body.append("strength", sStrengthInput.value);
  body.append("output_format", outputFormat);

  sSubmitBtn.disabled = true;
  sStatus.textContent = `Analizando y alineando ${targets.length} pista(s)… puede tardar.`;
  sResults.innerHTML = "";
  sResultDownload.hidden = true;

  try {
    const response = await fetch(`${apiBase}/api/quantize/align_session`, {
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
    sResultDownload.href = zipUrl;
    sResultDownload.download = "sesion_alineada.zip";
    sResultDownload.hidden = false;

    let report = [];
    try {
      const reportBytes = extractStoredZipEntry(zipBuffer, "report.json");
      report = JSON.parse(new TextDecoder().decode(reportBytes));
    } catch (reportErr) {
      sStatus.textContent = `Listo, pero no pude leer el detalle por pista (${reportErr.message}). Descargá el ZIP igual.`;
    }

    for (const entry of report) {
      try {
        const wavBytes = extractStoredZipEntry(zipBuffer, entry.file);
        const mime = entry.file.endsWith(".mp3") ? "audio/mpeg" : "audio/wav";
        const wavUrl = URL.createObjectURL(new Blob([wavBytes], { type: mime }));

        const row = document.createElement("div");
        row.className = "session-track";
        const label = document.createElement("p");
        label.textContent = `${entry.file} — ${entry.segments} segmentos` +
          (entry.clamped > 0 ? ` (${entry.clamped} limitados por estiramiento extremo)` : "");
        const player = document.createElement("audio");
        player.controls = true;
        player.src = wavUrl;
        row.appendChild(label);
        row.appendChild(player);
        sResults.appendChild(row);
      } catch (entryErr) {
        // si una pista puntual no se puede extraer, seguimos con las demas
        const row = document.createElement("p");
        row.textContent = `${entry.file}: no se pudo cargar el preview (${entryErr.message})`;
        sResults.appendChild(row);
      }
    }

    sStatus.textContent = `Listo — ${report.length || targets.length} pista(s) alineadas contra la referencia. Descargá el ZIP para reimportarlas a Logic.`;
  } catch (err) {
    sStatus.textContent = `Error: ${err.message}`;
  } finally {
    sSubmitBtn.disabled = false;
  }
});
