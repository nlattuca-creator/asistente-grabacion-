// Extrae una entrada sin comprimir (ZIP_STORED) de un ZIP, leyendo el local
// file header directamente. Suficiente para nuestro propio backend (que
// siempre escribe ZIP_STORED, sin data descriptors) — no es un lector de
// ZIP genérico, no soporta compresión ni streaming.
function extractStoredZipEntry(buffer, targetName) {
  const view = new DataView(buffer);
  const decoder = new TextDecoder();
  let offset = 0;

  while (offset + 30 <= buffer.byteLength) {
    const signature = view.getUint32(offset, true);
    if (signature !== 0x04034b50) break; // fin de los local file headers

    const compressionMethod = view.getUint16(offset + 8, true);
    const compressedSize = view.getUint32(offset + 18, true);
    const nameLength = view.getUint16(offset + 26, true);
    const extraLength = view.getUint16(offset + 28, true);

    const nameStart = offset + 30;
    const name = decoder.decode(new Uint8Array(buffer, nameStart, nameLength));
    const dataStart = nameStart + nameLength + extraLength;

    if (name === targetName) {
      if (compressionMethod !== 0) {
        throw new Error(`"${targetName}" está comprimido, no se puede extraer sin una librería de ZIP`);
      }
      return buffer.slice(dataStart, dataStart + compressedSize);
    }

    offset = dataStart + compressedSize;
  }

  throw new Error(`no se encontró "${targetName}" en el ZIP`);
}
