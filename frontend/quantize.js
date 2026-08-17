const qForm = document.getElementById("quantize-form");
const qStatus = document.getElementById("q-status");
const qPlayer = document.getElementById("q-result-player");
const qDownloadLink = document.getElementById("q-result-download");
const qSubmitBtn = document.getElementById("q-submit-btn");
const qStrengthInput = document.getElementById("q-strength");
const qStrengthValue = document.getElementById("q-strength-value");
const qEditor = document.getElementById("q-editor");
const qWaveReference = document.getElementById("q-wave-reference");
const qWaveTarget = document.getElementById("q-wave-target");
const qWaveTargetTrack = document.getElementById("q-wave-target-track");
const qResetBtn = document.getElementById("q-reset-btn");
const qApplyBtn = document.getElementById("q-apply-btn");

qStrengthInput.addEventListener("input", () => {
  qStrengthValue.textContent = `${qStrengthInput.value}%`;
});

// Estado del editor de la sesión de análisis actual.
let qCurrentEvents = []; // [{origTime, suggestedTime, targetTime}]
let qCurrentDuration = 0;
let qCurrentTargetFile = null;
let qMarkerTrack = null;

function apiBase() {
  return document.getElementById("api_base").value.replace(/\/$/, "");
}

qForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const reference = document.getElementById("q-reference").files[0];
  const target = document.getElementById("q-target").files[0];
  if (!reference || !target) return;

  const body = new FormData();
  body.append("reference", reference);
  body.append("target", target);
  body.append("subdivision", document.getElementById("q-subdivision").value);
  body.append("strength", qStrengthInput.value);

  qSubmitBtn.disabled = true;
  qStatus.textContent = "Analizando tempo, grilla y ataques…";
  qEditor.hidden = true;
  qPlayer.hidden = true;
  qDownloadLink.hidden = true;

  try {
    const response = await fetch(`${apiBase()}/api/quantize/analyze`, {
      method: "POST",
      body,
    });

    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Error ${response.status}`);

    qCurrentDuration = data.duration;
    qCurrentTargetFile = target;
    qCurrentEvents = data.events.map((ev) => ({
      origTime: ev.orig_time,
      suggestedTime: ev.suggested_time,
      targetTime: ev.suggested_time,
    }));

    await renderEditor(reference, target, data.grid);

    qStatus.textContent = qCurrentEvents.length
      ? `${qCurrentEvents.length} ataques detectados. Escuchá, arrastrá los puntos si hace falta, y aplicá.`
      : "No se detectaron ataques para alinear en el audio a corregir — se puede aplicar igual, no va a cambiar nada.";
  } catch (err) {
    qStatus.textContent = `Error: ${err.message}`;
  } finally {
    qSubmitBtn.disabled = false;
  }
});

async function renderEditor(referenceFile, targetFile, grid) {
  // Mostrar el contenedor ANTES de medir/dibujar: un elemento con
  // hidden (display:none) mide clientWidth=0, así que el canvas quedaba
  // de 1px si lo medíamos con el editor todavía oculto.
  qEditor.hidden = false;

  const targetWidth = Math.max(300, qWaveTargetTrack.clientWidth || 600);

  const [refPeaks, targetPeaks] = await Promise.all([
    decodeAudioPeaks(referenceFile, targetWidth),
    decodeAudioPeaks(targetFile, targetWidth),
  ]);

  drawWaveform(qWaveReference, refPeaks.peaks, "#7c9eff");
  drawTicks(qWaveReference, grid, refPeaks.duration, "rgba(255,255,255,0.25)", 1);

  drawWaveform(qWaveTarget, targetPeaks.peaks, "#6fd48c");
  drawTicks(
    qWaveTarget,
    qCurrentEvents.map((ev) => ev.origTime),
    qCurrentDuration,
    "rgba(255,255,255,0.4)",
    2,
  );

  qWaveTargetTrack.querySelectorAll(".wave-marker").forEach((el) => el.remove());
  qMarkerTrack = createMarkerTrack(qWaveTargetTrack, qCurrentEvents, qCurrentDuration, () => {});
}

qResetBtn.addEventListener("click", () => {
  if (qMarkerTrack) qMarkerTrack.reset();
  qStatus.textContent = "Restablecido a las sugerencias automáticas.";
});

qApplyBtn.addEventListener("click", async () => {
  if (!qCurrentTargetFile) return;

  const outputFormat = document.getElementById("q-output_format").value;
  const events = qCurrentEvents.map((ev) => ({
    orig_time: ev.origTime,
    target_time: ev.targetTime,
  }));

  const body = new FormData();
  body.append("target", qCurrentTargetFile);
  body.append("events", JSON.stringify(events));
  body.append("output_format", outputFormat);

  qApplyBtn.disabled = true;
  qStatus.textContent = "Aplicando…";
  qPlayer.hidden = true;
  qDownloadLink.hidden = true;

  try {
    const response = await fetch(`${apiBase()}/api/quantize/render`, {
      method: "POST",
      body,
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => null);
      throw new Error(errorBody?.detail || `Error ${response.status}`);
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);

    qPlayer.src = url;
    qPlayer.hidden = false;

    const disposition = response.headers.get("content-disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    qDownloadLink.href = url;
    qDownloadLink.download = match ? match[1] : `resultado.${outputFormat}`;
    qDownloadLink.hidden = false;

    const segments = response.headers.get("x-quantize-segments");
    const clamped = response.headers.get("x-quantize-clamped");
    let msg = `Listo — ${segments} segmentos.`;
    if (clamped && Number(clamped) > 0) {
      msg += ` ${clamped} necesitaban un estiramiento tan extremo que se limitó (para no destruir el audio).`;
    }
    qStatus.textContent = msg;
  } catch (err) {
    qStatus.textContent = `Error: ${err.message}`;
  } finally {
    qApplyBtn.disabled = false;
  }
});
