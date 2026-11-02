package com.evidencia.app

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.text.DateFormat
import java.util.Date

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(vm: AppViewModel, onBack: () -> Unit, onOpened: () -> Unit) {
    var query by rememberSaveable { mutableStateOf("") }
    var confirmAll by remember { mutableStateOf(false) }
    val shown = remember(vm.conversations, query) {
        val q = query.trim()
        if (q.isEmpty()) vm.conversations
        else vm.conversations.filter { c ->
            c.title.contains(q, ignoreCase = true) ||
                c.turns.any { t ->
                    t.question.contains(q, ignoreCase = true) ||
                        ((t.status as? Status.Done)?.answer?.text?.contains(q, ignoreCase = true) == true)
                }
        }
    }
    val fmt = remember { DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT) }

    Scaffold(topBar = {
        TopAppBar(
            title = { Text("Historial") },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Volver") } },
            actions = { if (vm.conversations.isNotEmpty()) TextButton({ confirmAll = true }) { Text("Borrar todo") } },
        )
    }) { pad ->
        Column(Modifier.padding(pad)) {
            OutlinedTextField(
                query, { query = it }, Modifier.fillMaxWidth().padding(16.dp),
                label = { Text("Buscar en el historial") }, singleLine = true,
            )
            if (shown.isEmpty()) {
                Text(
                    if (vm.conversations.isEmpty()) "Aún no hay conversaciones guardadas." else "Sin resultados.",
                    Modifier.padding(horizontal = 16.dp),
                )
            } else {
                LazyColumn {
                    items(shown, key = { it.id }) { c ->
                        ListItem(
                            headlineContent = { Text(c.title, maxLines = 2) },
                            supportingContent = { Text("${fmt.format(Date(c.updatedAt))} · ${c.turns.size} consulta(s)") },
                            trailingContent = {
                                IconButton({ vm.delete(c.id) }) { Icon(Icons.Default.Delete, "Borrar conversación") }
                            },
                            modifier = Modifier.clickable { vm.open(c.id); onOpened() },
                        )
                    }
                }
            }
        }
    }

    if (confirmAll) AlertDialog(
        onDismissRequest = { confirmAll = false },
        title = { Text("¿Borrar todo el historial?") },
        text = { Text("Se eliminarán todas las conversaciones guardadas en este móvil. No se puede deshacer.") },
        confirmButton = { TextButton({ vm.deleteAll(); confirmAll = false }) { Text("Borrar") } },
        dismissButton = { TextButton({ confirmAll = false }) { Text("Cancelar") } },
    )
}
