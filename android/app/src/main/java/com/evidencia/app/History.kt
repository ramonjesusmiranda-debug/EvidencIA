package com.evidencia.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption

data class Conversation(val id: String, val title: String, val updatedAt: Long, val turns: List<Turn>)

/**
 * Historial en archivos JSON dentro de filesDir (privado a la app, excluido de copias y transferencias).
 * Un archivo por conversación, escritura atómica. Solo se guardan turnos completados.
 */
class HistoryStore(context: Context) {
    private val dir = File(context.filesDir, "history").apply { mkdirs() }

    fun loadAll(): List<Conversation> =
        dir.listFiles { f -> f.name.endsWith(".json") }.orEmpty()
            .mapNotNull { f -> runCatching { parse(JSONObject(f.readText())) }.getOrNull() }
            .sortedByDescending { it.updatedAt }

    fun save(c: Conversation) {
        val tmp = File(dir, "${c.id}.tmp")
        tmp.writeText(toJson(c).toString())
        Files.move(tmp.toPath(), File(dir, "${c.id}.json").toPath(),
            StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
    }

    fun delete(id: String) { File(dir, "$id.json").delete() }

    fun deleteAll() { dir.listFiles()?.forEach { it.delete() } }

    private fun toJson(c: Conversation) = JSONObject()
        .put("v", VERSION).put("id", c.id).put("title", c.title).put("updatedAt", c.updatedAt)
        .put("turns", JSONArray().also { arr ->
            c.turns.forEach { t ->
                val done = t.status as? Status.Done ?: return@forEach
                arr.put(JSONObject().put("id", t.id).put("question", t.question).put("answer", done.answer.toJson()))
            }
        })

    private fun parse(j: JSONObject): Conversation? {
        if (j.optInt("v") != VERSION) return null // versión desconocida: se ignora, no se rompe
        val ts = j.getJSONArray("turns")
        return Conversation(
            j.getString("id"), j.getString("title"), j.getLong("updatedAt"),
            List(ts.length()) {
                val t = ts.getJSONObject(it)
                Turn(t.getLong("id"), t.getString("question"), Status.Done(answerFromJson(t.getJSONObject("answer"))))
            },
        )
    }

    private companion object { const val VERSION = 1 }
}
