package com.evidencia.app

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.UUID
import java.util.concurrent.Executors

sealed interface Status {
    data object Loading : Status
    data class Done(val answer: Answer) : Status
    data class Failed(val message: String) : Status
}

data class Turn(val id: Long, val question: String, val status: Status)

class AppViewModel(app: Application) : AndroidViewModel(app) {
    private val settingsStore = SettingsStore(app)
    private val history = HistoryStore(app)
    private var job: Job? = null

    // TODOS los accesos al historial pasan por un único hilo FIFO: un guardado en cola nunca puede ejecutarse
    // después de un borrado posterior (resucitaría una conversación borrada).
    private val io = Executors.newSingleThreadExecutor().asCoroutineDispatcher()
    private val removedIds = mutableSetOf<String>()
    private var clearedAll = false

    var settings by mutableStateOf(settingsStore.load())
        private set
    val turns = mutableStateListOf<Turn>()
    var conversations by mutableStateOf<List<Conversation>>(emptyList())
        private set
    var currentId by mutableStateOf<String?>(null)
        private set
    var connectionMessage by mutableStateOf<String?>(null)
        private set

    val busy: Boolean get() = turns.lastOrNull()?.status == Status.Loading

    init {
        viewModelScope.launch {
            val loaded = withContext(io) { history.loadAll() }
            if (clearedAll) return@launch
            // se mezcla con lo que ya se haya guardado/borrado mientras cargaba
            val have = conversations.map { it.id }.toSet()
            conversations = (conversations + loaded.filter { it.id !in have && it.id !in removedIds })
                .sortedByDescending { it.updatedAt }
        }
    }

    override fun onCleared() { io.close() }

    fun saveSettings(s: AppSettings) {
        settingsStore.save(s)
        settings = settingsStore.load()
    }

    /** Contexto para la pregunta de seguimiento: turnos completados de la conversación abierta. */
    private fun historyPayload(): List<HistoryItem> =
        turns.mapNotNull { t ->
            val a = (t.status as? Status.Done)?.answer ?: return@mapNotNull null
            HistoryItem(
                t.question.take(1000),
                if (a.insufficient) "" else a.text.take(1500),
                if (a.insufficient) emptyList() else a.citations.map { it.pmid }.take(10),
            )
        }.takeLast(8)

    fun ask(question: String) {
        val q = question.trim()
        if (q.length < 5 || busy) return
        val convId = currentId ?: UUID.randomUUID().toString().also { currentId = it }
        val id = System.nanoTime()
        val payload = historyPayload()
        turns.add(Turn(id, q, Status.Loading))
        val s = settings
        job = viewModelScope.launch {
            val status: Status = try {
                Status.Done(Api.ask(s, q, payload))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                Status.Failed(e.message ?: "Error de red")
            }
            val i = turns.indexOfFirst { it.id == id }
            if (i < 0) return@launch
            // se muestra (y se guarda) la pregunta ya filtrada por el servidor
            val shown = (status as? Status.Done)?.answer?.questionUsed?.takeIf { it.isNotBlank() } ?: q
            turns[i] = turns[i].copy(question = shown, status = status)
            if (status is Status.Done) persist(convId)
        }
    }

    private fun persist(convId: String) {
        if (!settings.saveHistory) return
        val done = turns.filter { it.status is Status.Done }
        if (done.isEmpty()) return
        val conv = Conversation(convId, done.first().question.take(60), System.currentTimeMillis(), done)
        conversations = listOf(conv) + conversations.filter { it.id != convId }
        viewModelScope.launch(io) { runCatching { history.save(conv) } }
    }

    private fun cancelInFlight() {
        job?.cancel()
        turns.removeAll { it.status == Status.Loading }
    }

    fun newConversation() {
        cancelInFlight()
        currentId = null
        turns.clear()
    }

    fun open(id: String) {
        val c = conversations.firstOrNull { it.id == id } ?: return
        cancelInFlight()
        currentId = c.id
        turns.clear()
        turns.addAll(c.turns)
    }

    fun delete(id: String) {
        removedIds += id
        conversations = conversations.filter { it.id != id }
        viewModelScope.launch(io) { runCatching { history.delete(id) } }
        if (currentId == id) newConversation()
    }

    fun deleteAll() {
        clearedAll = true
        conversations = emptyList()
        viewModelScope.launch(io) { runCatching { history.deleteAll() } }
        newConversation()
    }

    fun testConnection(draft: AppSettings) {
        connectionMessage = "Probando…"
        viewModelScope.launch {
            connectionMessage = try { Api.check(draft) } catch (e: Exception) { "No se pudo conectar: ${e.message}" }
        }
    }

    fun dismissConnectionMessage() { connectionMessage = null }
}
