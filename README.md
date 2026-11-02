# EvidencIA

Preguntas clínicas -> respuesta breve con citas de PubMed verificadas.

- `backend/`: FastAPI. Pregunta -> consulta PubMed (Claude) -> E-utilities -> respuesta solo con esas fuentes -> verificador determinista (cita existente, cifras presentes en el resumen) -> `/ask`.
- `android/`: Kotlin + Compose, Material You (colores dinámicos), pantalla de consulta con preguntas de seguimiento, historial local y ajustes (servidor, Ollama local o clave de API). **No compilado todavía** (sin Android SDK en el entorno de creación).

## Backend
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn httpx anthropic pytest
.venv/bin/python -m pytest -q
ANTHROPIC_API_KEY=... [NCBI_API_KEY=...] [APP_TOKEN=...] .venv/bin/uvicorn app.main:app --port 8000
```
## Android
Abrir `android/` en Android Studio; ajustar `API_URL`/`APP_TOKEN` en `app/build.gradle.kts`. Desplegar el backend con HTTPS antes de usar en dispositivos reales (y quitar `usesCleartextTraffic`).

## Sin clave de API (modelo local con Ollama)
```bash
ollama pull qwen2.5:7b-instruct
LLM_BACKEND=ollama [OLLAMA_MODEL=...] [OLLAMA_HOST=http://localhost:11434] .venv/bin/uvicorn app.main:app --port 8000
```
El verificador se aplica igual; con modelos pequeños espera más frases omitidas.

## Seguridad / despliegue
- La app envía al servidor el proveedor, el modelo y (si la usas) la clave de API en cada consulta: usa HTTPS fuera de tu red local. Se guarda en preferencias privadas **sin cifrar** (TODO: Keystore).
- Define `APP_TOKEN` en el servidor antes de exponerlo más allá de tu LAN: sin él, un Ollama remoto indicado por la app es rechazado (evita SSRF), y quien alcance el servidor podría gastar tu clave. `ALLOW_CLIENT_LLM_CONFIG=0` desactiva por completo la configuración desde la app.
- "Probar servidor y modelo" llama a `POST /check`: comprueba Ollama alcanzable y modelo descargado, o clave y modelo válidos (sin gastar tokens).

## Contexto e historial
- **Seguimiento:** la app envía las preguntas previas de la conversación (y la respuesta de las 3 últimas, sin marcadores `[n]`) más los PMID citados. El servidor redacta, reescribe la pregunta como autónoma (`standalone_question`, visible en la app como "Interpretada como"), busca en PubMed y reutiliza las fuentes citadas antes (máx. 10). El historial **no es fuente**: la verificación se hace solo contra las fuentes actuales.
- **Filtro de datos identificativos** (`backend/app/phi.py`): DNI/NIE, correo, teléfono, fechas completas, nº de historia y nombres tras paciente/Sr./Sra./D./Dña. Se aplica antes de cualquier llamada a un LLM o a PubMed y no se registra la pregunta. Es heurístico: no detecta nombres sin indicador.
- **Historial local:** archivos JSON privados de la app (`filesDir/history`), excluidos de copia en la nube y de la transferencia entre dispositivos; se puede desactivar y borrar desde Ajustes.
- `scripts/smoke.py` incluye un par de seguimiento que imprime la pregunta reescrita.
