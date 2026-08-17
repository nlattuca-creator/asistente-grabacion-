# audio-companion

Compañero de edición, mezcla y mastering asistido por IA. Le subís audio,
le pedís cambios (tempo, separación de pistas, sugerencias de composición) y
vas iterando el trabajo con él.

## Estado

**Fase 1 (implementada):** edición de tempo/pitch. Subís un audio (por ahora
pensado para voz sola), le decís el tempo objetivo, y te devuelve el archivo
re-temporizado **preservando el tono** (no es un simple "pitch up/down" al
acelerar — es time-stretching real vía [Rubber Band](https://breakfastquay.com/rubberband/)).

**Cuantizado (implementado):** alineá el timing de una pista (ej. voz) a la
grilla rítmica de otra (ej. piano) — como el Flex Time + Quantize de Logic,
pero enganchado a un archivo de referencia real. No estira todo parejo:
detecta cada ataque de la voz y lo mueve individualmente al punto de grilla
más cercano. Ver detalle abajo.

**Creador de batería (implementado, sin probar contra Claude real):**
describís un estilo en texto libre + BPM, y te devuelve un ZIP con un MIDI
(para usar en Drummer o tu kit en Logic, con tus propios sonidos) y un
preview en audio sintetizado acá mismo, solo para escuchar la idea. Ver
detalle abajo.

**Fase 2 (planeada):** separación de stems (voz/instrumentos) sobre una mezcla,
para poder ajustar niveles de cada pista por separado. Necesita un modelo tipo
Demucs corriendo server-side — no anda bien en el browser.

**Fase 3 (planeada):** sugerencias de composición/arreglo/mezcla con Claude,
usando como contexto el audio ya analizado (tempo, tonalidad, estructura).

**Asistente de chat (implementado, sin probar contra Claude real):** ventana
de diálogo flotante para preguntas de conocimiento general sobre producción
musical y Logic Pro (atajos, dónde está tal función, cómo se hace tal cosa).
No analiza tu audio — para eso es la fase 3. Requiere una API key de
Anthropic propia de este proyecto (ver abajo).

La arquitectura (backend Python separado del frontend) está pensada desde el
día 1 para soportar las tres fases sin reescribir nada: cada módulo nuevo es
un router más en `backend/app/modules/`.

## Arquitectura

```
audio-companion/
  backend/            FastAPI (Python) — todo el procesamiento pesado de audio
    app/
      main.py          entrypoint, monta los routers de cada módulo
      modules/
        tempo.py        Fase 1: tempo/pitch (rubberband + ffmpeg)
        quantize.py      Cuantizado: alinea una pista a la grilla de otra (librosa + rubberband)
        beatmaker.py     Creador de batería: patrón (Claude) -> MIDI + preview sintetizado
        stems.py         Fase 2: separación de stems (placeholder)
        compose.py       Fase 3: sugerencias con Claude (placeholder)
        assistant.py     Chat de Q&A general (Claude, sin analizar audio)
    requirements.txt
    .env.example
  frontend/            Página web simple (HTML/JS vanilla, sin build step)
    index.html
    app.js              lógica del formulario de tempo
    quantize.js          lógica del formulario de cuantizado
    beatmaker.js          lógica del formulario de batería
    zip-lite.js           extrae una entrada de un ZIP sin comprimir (para el preview)
    chat.js              lógica del panel de chat flotante
    style.css
```

Por qué backend separado en vez de todo en el browser: la separación de
stems (fase 2) necesita modelos pesados (tipo Demucs) que no corren bien en
JS/WASM. Arrancar con esa arquitectura desde la fase 1, aunque el módulo de
tempo sea liviano, evita tener que reescribir todo cuando lleguemos a fase 2.

## Cómo correrlo local

Requiere `ffmpeg` y `rubberband-cli` instalados en el sistema (Debian/Ubuntu:
`sudo apt-get install ffmpeg rubberband-cli`).

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend: el backend ya sirve `frontend/` en `/` (probá `http://localhost:8000`
directo). Si preferís abrir `frontend/index.html` como archivo local aparte,
el campo "URL del backend" se completa solo con `http://localhost:8000`.

## Deploy en un VPS (Ubuntu/Debian)

```bash
ssh root@TU_IP

apt update && apt install -y ffmpeg rubberband-cli python3-venv git

mkdir -p /opt && cd /opt
git clone https://github.com/nlattuca-creator/asistente-grabacion- asistente-grabacion
cd asistente-grabacion/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# (opcional, para el chat) cp .env.example .env && editar con la API key

cp /opt/asistente-grabacion/deploy/asistente-grabacion.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now asistente-grabacion
systemctl status asistente-grabacion   # debe decir "active (running)"
```

Abrí el puerto 8000 si el firewall lo bloquea:

```bash
ufw allow 8000/tcp   # si usás ufw
```

Si el VPS es Vultr y el puerto sigue sin responder desde afuera después de
esto, revisá también el **Firewall Group** del panel de Vultr (es un
firewall aparte, a nivel de red, que puede estar bloqueando el puerto aunque
`ufw` lo permita).

Con el servicio corriendo, entrás directo a `http://TU_IP:8000`.

**Para actualizar** después de que suba cambios nuevos al repo:

```bash
cd /opt/asistente-grabacion
git pull
backend/.venv/bin/pip install -r backend/requirements.txt   # solo si cambió requirements.txt
systemctl restart asistente-grabacion
```

## Módulo 1: tempo/pitch

`POST /api/tempo/process` — multipart form:
- `file`: archivo de audio (wav, mp3, m4a, etc.)
- `tempo_ratio` **o** (`bpm_from` + `bpm_to`): a cuánto cambiar el tempo.
  Ej: `tempo_ratio=1.15` = 15% más rápido. `bpm_from=90&bpm_to=100` calcula
  el ratio solo.
- `output_format` (opcional, default `wav`): `wav` o `mp3`.

Devuelve el archivo procesado. El pitch se preserva automáticamente (eso es
lo que diferencia esto de simplemente acelerar el archivo).

`POST /api/tempo/detect` — multipart form con `file`. Devuelve
`{"bpm": 120.2}`, el BPM estimado con [librosa](https://librosa.org/). En el
frontend, el botón "Detectar automáticamente" completa el campo BPM original
con esto (queda editable — la detección puede fallar por "error de octava",
detectando el doble o la mitad del tempo real, típico en cualquier algoritmo
de beat tracking).

## Cuantizado: alinear una pista a la grilla de otra

`POST /api/quantize/align` — multipart form:
- `reference`: audio que marca el tempo (ej. piano ya grabado).
- `target`: audio a alinear (ej. voz).
- `subdivision` (1-8, default 4): a qué subdivisión del beat cuantiza
  (1 = negras, 2 = corcheas, 4 = semicorcheas, 8 = fusas).
- `strength` (0-100, default 100): qué tan fuerte cuantiza. 100 = pega cada
  ataque exactamente a la grilla. Valores más bajos lo acercan sin pegarlo
  del todo (mezcla entre el timing original y el cuantizado), útil si 100%
  suena robótico.
- `output_format` (`wav` o `mp3`, default `wav`).

Devuelve el `target` con el timing ajustado. Headers de respuesta:
`X-Quantize-Segments` (cuántos tramos se procesaron) y `X-Quantize-Clamped`
(cuántos de esos tramos necesitaban un estiramiento tan extremo que se
limitó para no destruir el audio — si este número es alto, esos tramos
puntuales van a sonar raros o no van a quedar perfectamente en grilla).

**Cómo funciona:** detecta la grilla de beats del `reference` con
`librosa.beat.beat_track`, detecta los "onsets" (ataques/sílabas) del
`target` con `librosa.onset.onset_detect`, calcula para cada onset el punto
de grilla más cercano, y estira/comprime individualmente cada segmento
entre onsets (con Rubber Band, preservando el tono) para que caiga ahí.

**Limitaciones a tener en cuenta:**
- Procesa en mono. Si tu voz está grabada en estéreo, el resultado sale
  mono — para maquetear no debería importar, pero no es un reemplazo de
  Flex Time para el master final.
- No soporta swing/triplets, solo subdivisiones rectas.
- Si el `reference` no tiene un pulso rítmico claro (ej. una pista muy
  ambient/rubato), la detección de grilla puede fallar o salir mal.
- Tramos que necesitarían estirarse/comprimirse más de 4x (o menos de 0.25x)
  se limitan a ese máximo en vez de fallar — mirá `X-Quantize-Clamped`.
- Archivos de hasta 10 minutos y 100MB, hasta 400 segmentos detectados.

## Creador de batería

`POST /api/beatmaker/generate` — multipart form:
- `style`: descripción libre del estilo (ej. "trap oscuro con hihats con
  rolls", "boom bap con swing", "reggaetón"). En español o inglés, lo que
  sea.
- `bpm` (40-240) **o** `reference` (archivo de audio — tu canción tal como
  va hasta ahora). Si mandás `reference` sin `bpm`, el BPM se detecta solo.
  Si mandás los dos, `bpm` gana pero igual se usa `reference` para sacar
  tonalidad/duración de contexto.
- `reference` (opcional): audio de la canción real. Se le saca tempo,
  tonalidad estimada y duración con librosa, y ese contexto se le pasa a
  Claude junto con `style` — así el patrón no se genera a ciegas, sabe
  sobre qué canción va a sonar. La tonalidad es aproximada (estimación por
  correlación de croma, puede fallar en temas con mucha ambigüedad
  armónica).
- `bars` (1-8, default 4).

Headers de respuesta: `X-Beatmaker-Bpm` (el BPM que terminó usando) y, si
mandaste `reference`, `X-Beatmaker-Key` (la tonalidad estimada).

Devuelve un `.zip` con:
- `pattern.mid` — el archivo para usar de verdad: arrastralo a un track de
  Drummer o a tu kit de batería en Logic y sonará con tus propios sonidos.
  Mapeo General MIDI en canal 10: kick=36, snare=38, hihat cerrado=42,
  hihat abierto=46, clap=39.
- `preview.wav` — render rápido con sonidos sintetizados en el momento (no
  es calidad de estudio), solo para escuchar la idea sin abrir Logic. El
  frontend lo reproduce automáticamente apenas termina de generar.
- `pattern.json` — el patrón crudo (qué instrumento suena en qué paso, con
  qué velocidad), por transparencia.

**Cómo funciona:** Claude genera UN patrón de 1 compás (16 pasos,
resolución de semicorchea) en JSON según el estilo pedido, y ese mismo
patrón se repite durante los `bars` compases (sin variación entre
compases ni fills — es un loop, no un arreglo completo). Si Claude no
devuelve JSON válido, se reintenta una vez antes de fallar.

**Limitaciones a tener en cuenta:**
- Patrón de 1 compás repetido, no hay variación/fills entre compases
  todavía.
- Solo 5 elementos: kick, snare, hihat cerrado, hihat abierto, clap — sin
  toms, crashes, percusión latina, etc.
- El preview es una síntesis muy simple (ruido filtrado + osciladores),
  pensada para dar una idea del groove, no para usar como sonido final.
- La tonalidad detectada del `reference` es una estimación aproximada, no
  perfecta.
- Necesita la misma `ANTHROPIC_API_KEY` que el asistente de chat (ver
  abajo).

## Asistente de chat

1. `cp backend/.env.example backend/.env`
2. Completar `ANTHROPIC_API_KEY` en ese `.env` (nunca se commitea — está en
   `.gitignore`). Opcionalmente `ASSISTANT_MODEL` (default `claude-sonnet-5`).
3. Reiniciar el backend. El botón 💬 abre el panel de chat en el frontend.

`POST /api/assistant/chat` — JSON `{"messages": [{"role": "user"|"assistant", "content": "..."}]}`.
El historial completo viaja desde el cliente en cada request (no hay estado
en el server). Devuelve `{"role": "assistant", "content": "..."}`.
