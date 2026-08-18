// Mezcla en el browser (Web Audio API, nada viaja al server) la referencia
// + el resultado ya corregido, para poder juzgar de oído si quedó en
// tiempo — escuchar la pista corregida sola no sirve para eso, hay que
// escucharla CONTRA lo que la tiene que acompañar.

function audioBufferToWavBlob(buffer) {
  const numChannels = buffer.numberOfChannels;
  const sampleRate = buffer.sampleRate;
  const byteLength = buffer.length * numChannels * 2 + 44;
  const arrayBuffer = new ArrayBuffer(byteLength);
  const view = new DataView(arrayBuffer);

  function writeString(offset, str) {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  }

  writeString(0, "RIFF");
  view.setUint32(4, byteLength - 8, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * numChannels * 2, true);
  view.setUint16(32, numChannels * 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, buffer.length * numChannels * 2, true);

  const channels = [];
  for (let ch = 0; ch < numChannels; ch++) channels.push(buffer.getChannelData(ch));

  let offset = 44;
  for (let i = 0; i < buffer.length; i++) {
    for (let ch = 0; ch < numChannels; ch++) {
      let sample = Math.max(-1, Math.min(1, channels[ch][i]));
      sample = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      view.setInt16(offset, sample, true);
      offset += 2;
    }
  }

  return new Blob([arrayBuffer], { type: "audio/wav" });
}

// referenceFile: File del audio de referencia (piano, etc).
// resultBlob: Blob del audio ya corregido (lo que devolvió /render).
// referenceGain/resultGain: 0-1, volumen relativo de cada uno en la mezcla
// (la referencia un poco más baja por default para que la pista corregida
// se escuche clara encima).
async function mixReferenceWithResult(referenceFile, resultBlob, referenceGain, resultGain) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const decodeCtx = new AudioContextClass();

  let refBuffer, resultBuffer;
  try {
    const [refArrayBuf, resultArrayBuf] = await Promise.all([
      referenceFile.arrayBuffer(),
      resultBlob.arrayBuffer(),
    ]);
    [refBuffer, resultBuffer] = await Promise.all([
      decodeCtx.decodeAudioData(refArrayBuf),
      decodeCtx.decodeAudioData(resultArrayBuf),
    ]);
  } finally {
    decodeCtx.close();
  }

  const sampleRate = 44100;
  const numChannels = 2;
  const length = Math.max(refBuffer.length, resultBuffer.length) + sampleRate; // +1s de cola
  const offlineCtx = new OfflineAudioContext(numChannels, length, sampleRate);

  const refSource = offlineCtx.createBufferSource();
  refSource.buffer = refBuffer;
  const refGainNode = offlineCtx.createGain();
  refGainNode.gain.value = referenceGain ?? 0.55;
  refSource.connect(refGainNode).connect(offlineCtx.destination);

  const resultSource = offlineCtx.createBufferSource();
  resultSource.buffer = resultBuffer;
  const resultGainNode = offlineCtx.createGain();
  resultGainNode.gain.value = resultGain ?? 0.9;
  resultSource.connect(resultGainNode).connect(offlineCtx.destination);

  refSource.start(0);
  resultSource.start(0);

  const mixedBuffer = await offlineCtx.startRendering();
  return audioBufferToWavBlob(mixedBuffer);
}
