const qForm = document.getElementById("quantize-form");
const qStatus = document.getElementById("q-status");
const qPlayer = document.getElementById("q-result-player");
const qDownloadLink = document.getElementById("q-result-download");
const qSubmitBtn = document.getElementById("q-submit-btn");
const qStrengthInput = document.getElementById("q-strength");
const qStrengthValue = document.getElementById("q-strength-value");

qStrengthInput.addEventListener("input", () => {
  qStrengthValue.textContent = `${qStrengthInput.value}%`;
});

qForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const reference = document.getElementById("q-reference").files[0];
  const target = document.getElementById("q-target").files[0];
  if (!reference || !target) return;

  const apiBase = document.getElementById("api_base").value.replace(/\/$/, "");
  const outputFormat = document.getElementById("q-output_format").value;

  const body = new FormData();
  body.append("reference", reference);
  body.append("target", target);
  body.append("subdivision", document.getElementById("q-subdivision").value);
  body.append("strength", qStrengthInput.value);
  body.append("output_format", outputFormat);

  qSubmitBtn.disabled = true;
  qStatus.textContent = "Analizando y alineando… puede tardar según la duración del audio.";
  qPlayer.hidden = true;
  qDownloadLink.hidden = true;

  try {
    const response = await fetch(`${apiBase}/api/quantize/align`, {
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
    let msg = `Listo — ${segments} segmentos alineados.`;
    if (clamped && Number(clamped) > 0) {
      msg += ` ${clamped} de esos segmentos necesitaban un estiramiento tan extremo que se limitó (para no destruir el audio) — puede que no queden perfectamente en grilla.`;
    }
    qStatus.textContent = msg;
  } catch (err) {
    qStatus.textContent = `Error: ${err.message}`;
  } finally {
    qSubmitBtn.disabled = false;
  }
});
