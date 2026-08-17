// Utilidades de waveform: decodificar audio en el browser (Web Audio API,
// nada del archivo viaja al server solo para dibujarlo), dibujarlo en un
// <canvas>, y manejar marcadores arrastrables (divs posicionados encima
// del canvas — más simple que hit-testing manual en el canvas).

async function decodeAudioPeaks(file, targetWidth) {
  const arrayBuffer = await file.arrayBuffer();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const audioCtx = new AudioContextClass();
  let audioBuffer;
  try {
    audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
  } finally {
    audioCtx.close();
  }

  const channelData = audioBuffer.getChannelData(0);
  const samplesPerPixel = Math.max(1, Math.floor(channelData.length / targetWidth));
  const peaks = new Float32Array(targetWidth);

  for (let i = 0; i < targetWidth; i++) {
    const start = i * samplesPerPixel;
    const end = Math.min(start + samplesPerPixel, channelData.length);
    let max = 0;
    for (let j = start; j < end; j++) {
      const v = Math.abs(channelData[j]);
      if (v > max) max = v;
    }
    peaks[i] = max;
  }

  return { peaks, duration: audioBuffer.duration };
}

function setupCanvas(canvas, cssHeight) {
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.parentElement.clientWidth;
  canvas.style.width = `${cssWidth}px`;
  canvas.style.height = `${cssHeight}px`;
  canvas.width = Math.max(1, Math.round(cssWidth * dpr));
  canvas.height = Math.max(1, Math.round(cssHeight * dpr));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width: cssWidth, height: cssHeight };
}

function drawWaveform(canvas, peaks, color) {
  const { ctx, width, height } = setupCanvas(canvas, canvas.dataset.height || 80);
  ctx.clearRect(0, 0, width, height);
  const mid = height / 2;
  ctx.fillStyle = color;
  for (let x = 0; x < width; x++) {
    const peakIndex = Math.floor((x / width) * peaks.length);
    const amp = Math.max(peaks[peakIndex] || 0, 0.02) * mid;
    ctx.fillRect(x, mid - amp, 1, amp * 2);
  }
  return { width, height };
}

function drawTicks(canvas, times, duration, color, lineWidth) {
  const ctx = canvas.getContext("2d");
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  ctx.strokeStyle = color;
  ctx.lineWidth = lineWidth || 1;
  for (const t of times) {
    if (t < 0 || t > duration) continue;
    const x = Math.round((t / duration) * width) + 0.5;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
}

// events: [{origTime, targetTime}] — crea un marcador arrastrable por cada
// uno (posicionado por targetTime), con un tope fijo mostrando origTime.
// onChange(index, newTargetTime) se llama en cada movimiento.
function createMarkerTrack(trackEl, events, duration, onChange) {
  const markers = events.map((ev, index) => {
    const marker = document.createElement("div");
    marker.className = "wave-marker";
    marker.style.left = `${(ev.targetTime / duration) * 100}%`;
    marker.title = `Original: ${ev.origTime.toFixed(2)}s`;

    const handle = document.createElement("div");
    handle.className = "wave-marker-handle";
    marker.appendChild(handle);

    trackEl.appendChild(marker);
    return marker;
  });

  function neighborBounds(index) {
    const minGap = 0.02;
    const prevTime = index === 0 ? 0 : events[index - 1].targetTime + minGap;
    const nextTime = index === events.length - 1 ? duration : events[index + 1].targetTime - minGap;
    return [Math.max(0, prevTime), Math.min(duration, nextTime)];
  }

  markers.forEach((marker, index) => {
    let dragging = false;

    marker.addEventListener("pointerdown", (event) => {
      dragging = true;
      marker.setPointerCapture(event.pointerId);
      marker.classList.add("dragging");
    });

    marker.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      const rect = trackEl.getBoundingClientRect();
      const fraction = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      let newTime = fraction * duration;
      const [min, max] = neighborBounds(index);
      newTime = Math.min(max, Math.max(min, newTime));

      events[index].targetTime = newTime;
      marker.style.left = `${(newTime / duration) * 100}%`;
      onChange(index, newTime);
    });

    function endDrag(event) {
      if (!dragging) return;
      dragging = false;
      marker.classList.remove("dragging");
      try { marker.releasePointerCapture(event.pointerId); } catch (e) { /* no-op */ }
    }

    marker.addEventListener("pointerup", endDrag);
    marker.addEventListener("pointercancel", endDrag);
  });

  return {
    reset() {
      events.forEach((ev, index) => {
        ev.targetTime = ev.suggestedTime;
        markers[index].style.left = `${(ev.targetTime / duration) * 100}%`;
      });
    },
  };
}
