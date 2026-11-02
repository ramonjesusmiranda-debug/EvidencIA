package com.evidencia.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class Citation(val n: Int, val pmid: String, val title: String, val journal: String, val year: String, val studyType: String, val url: String)
data class Answer(
    val text: String,
    val insufficient: Boolean,
    val citations: List<Citation>,
    val omitted: Int,
    val disclaimer: String,
    val questionUsed: String,    // pregunta tras el filtro de datos identificativos
    val standalone: String,      // cómo interpretó el servidor la pregunta con el contexto
    val redactions: List<String>, // tipos de dato eliminados
)

/** Turno previo que se envía como contexto. */
data class HistoryItem(val question: String, val answer: String, val pmids: List<String>)

/** Mismo esquema JSON que la API: se reutiliza para guardar el historial en el móvil. */
fun answerFromJson(j: JSONObject): Answer {
    val cs = j.getJSONArray("citations")
    val rs = j.optJSONArray("redactions") ?: JSONArray()
    return Answer(
        text = j.getString("answer"),
        insufficient = j.getBoolean("insufficient_evidence"),
        citations = List(cs.length()) {
            val x = cs.getJSONObject(it)
            Citation(x.getInt("n"), x.getString("pmid"), x.getString("title"), x.getString("journal"),
                x.getString("year"), x.getString("study_type"), x.getString("url"))
        },
        omitted = j.optInt("omitted_unverified", 0),
        disclaimer = j.optString("disclaimer"),
        questionUsed = j.optString("question_used"),
        standalone = j.optString("standalone_question"),
        redactions = List(rs.length()) { rs.getString(it) },
    )
}

fun Answer.toJson(): JSONObject = JSONObject()
    .put("answer", text)
    .put("insufficient_evidence", insufficient)
    .put("citations", JSONArray().also { arr ->
        citations.forEach {
            arr.put(JSONObject().put("n", it.n).put("pmid", it.pmid).put("title", it.title).put("journal", it.journal)
                .put("year", it.year).put("study_type", it.studyType).put("url", it.url))
        }
    })
    .put("omitted_unverified", omitted)
    .put("disclaimer", disclaimer)
    .put("question_used", questionUsed)
    .put("standalone_question", standalone)
    .put("redactions", JSONArray(redactions))

object Api {
    private fun open(s: AppSettings, path: String): HttpURLConnection =
        (URL(s.backendUrl.trimEnd('/') + path).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            // una consulta con contexto hace hasta 4 llamadas al modelo; un Ollama en CPU es lento
            readTimeout = 1_200_000
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            if (s.appToken.isNotEmpty()) setRequestProperty("X-App-Token", s.appToken)
        }

    private fun HttpURLConnection.errorDetail(): String {
        val body = runCatching { errorStream?.bufferedReader()?.readText() }.getOrNull().orEmpty()
        val detail = runCatching { JSONObject(body).optString("detail") }.getOrNull().orEmpty()
        return "Error del servidor ($responseCode)" + if (detail.isNotEmpty()) ": $detail" else ""
    }

    private fun llmJson(s: AppSettings): JSONObject = when (s.provider) {
        Provider.CLAUDE -> JSONObject().put("provider", "claude").apply {
            if (s.claudeApiKey.isNotBlank()) put("api_key", s.claudeApiKey)
            if (s.claudeModel.isNotBlank()) put("model", s.claudeModel)
        }
        Provider.OLLAMA -> JSONObject().put("provider", "ollama").apply {
            if (s.ollamaHost.isNotBlank()) put("ollama_host", s.ollamaHost)
            if (s.ollamaModel.isNotBlank()) put("model", s.ollamaModel)
        }
    }

    /** Pregunta al servidor si Ollama/la clave y el modelo configurados funcionan (sin gastar tokens). */
    suspend fun check(s: AppSettings): String = withContext(Dispatchers.IO) {
        val c = open(s, "/check")
        try {
            c.outputStream.use { it.write(JSONObject().put("llm", llmJson(s)).toString().toByteArray()) }
            if (c.responseCode !in 200..299) error(c.errorDetail())
            JSONObject(c.inputStream.bufferedReader().readText()).optString("message", "Configuración correcta")
        } finally { c.disconnect() }
    }

    suspend fun ask(s: AppSettings, question: String, history: List<HistoryItem>): Answer = withContext(Dispatchers.IO) {
        val c = open(s, "/ask")
        try {
            val h = JSONArray()
            history.forEach {
                h.put(JSONObject().put("question", it.question).put("answer", it.answer).put("pmids", JSONArray(it.pmids)))
            }
            val body = JSONObject().put("question", question).put("history", h).put("llm", llmJson(s))
            c.outputStream.use { it.write(body.toString().toByteArray()) }
            if (c.responseCode !in 200..299) error(c.errorDetail())
            answerFromJson(JSONObject(c.inputStream.bufferedReader().readText()))
        } finally { c.disconnect() }
    }
}
