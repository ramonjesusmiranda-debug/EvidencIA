package com.evidencia.app

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedCard
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(vm: AppViewModel, onOpenSettings: () -> Unit, onOpenHistory: () -> Unit) {
    var input by rememberSaveable { mutableStateOf("") }
    val listState = rememberLazyListState()
    LaunchedEffect(vm.turns.size) { if (vm.turns.isNotEmpty()) listState.animateScrollToItem(vm.turns.lastIndex) }

    fun send() { if (!vm.busy && input.trim().length >= 5) { vm.ask(input); input = "" } }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("EvidencIA") },
                navigationIcon = { IconButton(onOpenHistory) { Icon(Icons.Default.Menu, "Historial") } },
                actions = {
                    IconButton(vm::newConversation) { Icon(Icons.Default.Add, "Nueva conversación") }
                    IconButton(onOpenSettings) { Icon(Icons.Default.Settings, "Ajustes") }
                },
            )
        },
        bottomBar = {
            Surface(tonalElevation = 3.dp) {
                Row(
                    Modifier.fillMaxWidth().navigationBarsPadding().imePadding().padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedTextField(
                        input, { input = it }, Modifier.weight(1f),
                        placeholder = {
                            Text(if (vm.turns.isEmpty()) "Pregunta clínica (sin datos de pacientes)" else "Pregunta de seguimiento…")
                        },
                        maxLines = 4,
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                        keyboardActions = KeyboardActions(onSend = { send() }),
                    )
                    FilledIconButton(::send, enabled = !vm.busy && input.trim().length >= 5) {
                        Icon(Icons.AutoMirrored.Filled.Send, "Enviar")
                    }
                }
            }
        },
    ) { pad ->
        if (vm.turns.isEmpty()) {
            Column(Modifier.padding(pad).padding(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Evidencia clínica con fuentes", style = MaterialTheme.typography.headlineSmall)
                Text(
                    "Respuestas basadas solo en resúmenes de PubMed, con cada afirmación verificada contra sus fuentes. " +
                        "Puedes hacer preguntas de seguimiento dentro de una conversación. " +
                        "Proveedor actual: ${if (vm.settings.provider == Provider.OLLAMA) "Ollama local" else "Claude (API)"}.",
                    style = MaterialTheme.typography.bodyLarge,
                )
                Text(
                    "Herramienta de apoyo a la decisión; no sustituye el juicio clínico. No introduzcas datos identificativos de pacientes: " +
                        "el servidor intenta ocultarlos, pero el filtro es heurístico y no detecta todos los nombres.",
                    style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        } else {
            LazyColumn(
                Modifier.padding(pad), state = listState,
                contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp),
            ) { items(vm.turns, key = { it.id }) { TurnItem(it) } }
        }
    }
}

@Composable
private fun TurnItem(t: Turn) {
    val ctx = LocalContext.current
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)) {
            Text(t.question, Modifier.padding(12.dp), color = MaterialTheme.colorScheme.onPrimaryContainer)
        }
        when (val s = t.status) {
            Status.Loading -> Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                Text("Buscando evidencia…")
            }
            is Status.Failed -> Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
                Text(s.message, Modifier.padding(12.dp), color = MaterialTheme.colorScheme.onErrorContainer)
            }
            is Status.Done -> {
                val a = s.answer
                if (a.redactions.isNotEmpty()) Text(
                    "Se ocultaron datos identificativos antes de procesar la pregunta: ${a.redactions.joinToString(", ")}.",
                    style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.tertiary,
                )
                // Solo si el contexto cambió la pregunta: así se detecta una mala interpretación.
                if (a.standalone.isNotBlank() && a.standalone != t.question) Text(
                    "Interpretada como: ${a.standalone}",
                    style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerHigh)) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(boldMarkdown(a.text))
                        if (a.omitted > 0) Text(
                            "Se omitieron ${a.omitted} afirmaciones no verificables contra las fuentes; revisa las fuentes citadas.",
                            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error,
                        )
                    }
                }
                a.citations.forEach { c ->
                    OutlinedCard(onClick = { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(c.url))) }, Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp)) {
                            Text("[${c.n}] ${c.title}", style = MaterialTheme.typography.titleSmall)
                            Text(
                                "${c.journal}, ${c.year} · ${c.studyType.ifBlank { "tipo n/d" }} · PMID ${c.pmid}",
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
                Text(a.disclaimer, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/** Interpreta solo **negrita**; el resto del texto se muestra tal cual. */
private fun boldMarkdown(t: String) = buildAnnotatedString {
    t.split("**").forEachIndexed { i, part ->
        if (i % 2 == 1) withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(part) } else append(part)
    }
}
