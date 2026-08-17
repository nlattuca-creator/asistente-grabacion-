const sessionForm = document.getElementById("session-form");
const sStatus = document.getElementById("s-status");
const sResults = document.getElementById("s-results");
const sResultDownload = document.getElementById("s-result-download");
const sSubmitBtn = document.getElementById("s-submit-btn");
const sTargetsInput = document.getElementById("s-targets");
const sTargetsStatus = document.getElementById("s-targets-status");
const sStrengthInput = document.getElementById("s-strength");
const sStrengthValue = document.getElementById("s-strength-value");
const sEditor = document.getElementById("s-editor");
const sWaveReference = document.getElementById("s-wave-reference");
const sTracksContainer = document.getElementById("s-tracks-container");
const sResetBtn = document.getElementById("s-reset-btn");
const sApplyBtn = document.getElementById("s-apply-btn");

sStrengthInput.addEventListener("input", () => {
  sStrengthValue.textContent = `${sStrengthInput.value}%`;
});

sTargetsInput.addEventListener("change", () => {
  const files = Array.from(sTargetsInput.files);
  sTargetsStatus.textContent = files.length
    ? `${files.length} pista(s): ${files.map((f) => f.name).join(", ")}`
    : "";
});

function sApiBase() {
  return document.getElementById("api_base").value.replace(/\/$/, "");
}

// Estado del análisis actual: un objeto por pista, en el mismo orden que
// los archivos subidos.
let sTracksState = []; // [{file, duration, events: [{origTime, suggestedTime, targetTime}], markerTrack}]

sessionForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const reference = document.getElementById("s-reference").files[0];
  const targets = Array.from(sTargetsInput.files);
  if (!reference || targets.length === 0) return;

  const body = new FormData();
  body.append("reference", reference);
  targets.forEach((file) => body.append("targets", file));
  body.append("subdivision", document.getElementById("s-subdivision").value);
  body.append("strength", sStrengthInput.value);

  sSubmitBtn.disabled = true;
  sStatus.textContent = `Analizando tempo, grilla y ataques de ${targets.length} pista(s)…`;
  sEditor.hidden = true;
  sResults.innerHTML = "";
  sResultDownload.hidden = true;

  try {
    const response = await fetch(`${sApiBase()}/api/quantize/analyze_session`, {
      method: "POST",
      body,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Error ${response.status}`);

    sTracksState = data.tracks.map((track, index) => ({
      file: targets[index],
      duration: track.duration,
      detectedBpm: track.detected_bpm,
      events: track.events.map((ev) => ({
        origTime: ev.orig_time,
        suggestedTime: ev.suggested_time,
        targetTime: ev.suggested_time,
      })),
      markerTrack: null,
    }));

    await renderSessionEditor(reference, data.grid, data.reference_bpm);

    const totalEvents = sTracksState.reduce((sum, t) => sum + t.events.length, 0);
    sStatus.textContent = `${totalEvents} ataques detectados en ${sTracksState.length} pista(s). Arrastrá los puntos si hace falta, y aplicá.`;
  } catch (err) {
    sStatus.textContent = `Error: ${err.message}`;
  } finally {
    sSubmitBtn.disabled = false;
  }
});

function formatBpmDiff(trackBpm, referenceBpm) {
  if (!trackBpm || trackBpm < 20) {
    return "no se detectó un pulso rítmico claro en esta pista (normal en voces sin acompañamiento propio) — el cuantizado por ataques igual funciona.";
  }
  const diff = trackBpm - referenceBpm;
  if (Math.abs(diff) < 1.5) return `${trackBpm} BPM (igual que la referencia)`;
  const sign = diff > 0 ? "+" : "";
  return `${trackBpm} BPM (${sign}${diff.toFixed(1)} vs. referencia — tempo global distinto, no solo desvíos puntuales)`;
}

async function renderSessionEditor(referenceFile, grid, referenceBpm) {
  // Mostrar antes de medir/dibujar (un contenedor hidden mide ancho 0).
  sEditor.hidden = false;

  const refWidth = Math.max(300, sWaveReference.parentElement.clientWidth || 600);
  const refPeaks = await decodeAudioPeaks(referenceFile, refWidth);
  drawWaveform(sWaveReference, refPeaks.peaks, "#7c9eff");
  drawTicks(sWaveReference, grid, refPeaks.duration, "rgba(255,255,255,0.25)", 1);

  const refPanel = sWaveReference.closest(".waveform-panel");
  let refBpmLine = refPanel.querySelector(".waveform-bpm");
  if (!refBpmLine) {
    refBpmLine = document.createElement("p");
    refBpmLine.className = "waveform-bpm hint";
    refPanel.insertBefore(refBpmLine, sWaveReference);
  }
  refBpmLine.textContent = `${referenceBpm} BPM detectado`;

  sTracksContainer.innerHTML = "";

  for (const track of sTracksState) {
    const panel = document.createElement("div");
    panel.className = "waveform-panel";

    const label = document.createElement("div");
    label.className = "waveform-label";
    label.textContent = track.file.name;
    panel.appendChild(label);

    const bpmLine = document.createElement("p");
    bpmLine.className = "waveform-bpm hint";
    bpmLine.textContent = formatBpmDiff(track.detectedBpm, referenceBpm);
    panel.appendChild(bpmLine);

    const waveTrack = document.createElement("div");
    waveTrack.className = "wave-track";
    const canvas = document.createElement("canvas");
    canvas.dataset.height = "90";
    waveTrack.appendChild(canvas);
    panel.appendChild(waveTrack);

    sTracksContainer.appendChild(panel);

    const trackWidth = Math.max(300, waveTrack.clientWidth || 600);
    const peaks = await decodeAudioPeaks(track.file, trackWidth);
    drawWaveform(canvas, peaks.peaks, "#6fd48c");
    drawTicks(canvas, track.events.map((ev) => ev.origTime), track.duration, "rgba(255,255,255,0.4)", 2);

    track.markerTrack = createMarkerTrack(waveTrack, track.events, track.duration, () => {});
  }
}

sResetBtn.addEventListener("click", () => {
  sTracksState.forEach((track) => track.markerTrack && track.markerTrack.reset());
  sStatus.textContent = "Restablecido a las sugerencias automáticas en todas las pistas.";
});

sApplyBtn.addEventListener("click", async () => {
  if (!sTracksState.length) return;

  const outputFormat = document.getElementById("s-output_format").value;
  const allEvents = sTracksState.map((track) =>
    track.events.map((ev) => ({ orig_time: ev.origTime, target_time: ev.targetTime })),
  );

  const body = new FormData();
  sTracksState.forEach((track) => body.append("targets", track.file));
  body.append("events", JSON.stringify(allEvents));
  body.append("output_format", outputFormat);

  sApplyBtn.disabled = true;
  sStatus.textContent = `Aplicando cambios a ${sTracksState.length} pista(s)…`;
  sResults.innerHTML = "";
  sResultDownload.hidden = true;

  try {
    const response = await fetch(`${sApiBase()}/api/quantize/render_session`, {
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
        const rowLabel = document.createElement("p");
        rowLabel.textContent = `${entry.file} — ${entry.segments} segmentos` +
          (entry.clamped > 0 ? ` (${entry.clamped} limitados por estiramiento extremo)` : "");
        const player = document.createElement("audio");
        player.controls = true;
        player.src = wavUrl;
        row.appendChild(rowLabel);
        row.appendChild(player);
        sResults.appendChild(row);
      } catch (entryErr) {
        const row = document.createElement("p");
        row.textContent = `${entry.file}: no se pudo cargar el preview (${entryErr.message})`;
        sResults.appendChild(row);
      }
    }

    sStatus.textContent = `Listo — ${report.length || sTracksState.length} pista(s) alineadas. Descargá el ZIP para reimportarlas a Logic.`;
  } catch (err) {
    sStatus.textContent = `Error: ${err.message}`;
  } finally {
    sApplyBtn.disabled = false;
  }
});
