package com.evidencia.app

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(vm: AppViewModel, onBack: () -> Unit) {
    var d by remember { mutableStateOf(vm.settings) }
    var showKey by remember { mutableStateOf(false) }
    var confirmDelete by remember { mutableStateOf(false) }
    val dirty = d != vm.settings
    DisposableEffect(Unit) { onDispose { vm.dismissConnectionMessage() } }

    Scaffold(topBar = {
        TopAppBar(
            title = { Text("Ajustes") },
            navigationIcon = { IconButton(onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Volver") } },
        )
    }) { pad ->
        if (confirmDelete) DeleteHistoryDialog({ vm.deleteAll(); confirmDelete = false }, { confirmDelete = false })
        Column(
            Modifier.padding(pad).verticalScroll(rememberScrollState()).padding(16.dp).imePadding(),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Section("Servidor EvidencIA") {
                Field(d.backendUrl, "URL del servidor", KeyboardType.Uri) { d = d.copy(backendUrl = it) }
                Field(d.appToken, "Token de acceso (opcional)", secret = true) { d = d.copy(appToken = it) }
                Text(
                    "Emulador: http://10.0.2.2:8000. Móvil físico: la IP de tu PC en la red local. " +
                        "Fuera de tu red usa HTTPS; la clave de API viaja al servidor en cada consulta.",
                    style = MaterialTheme.typography.bodySmall,
                )
                OutlinedButton({ vm.testConnection(d) }) { Text("Probar servidor y modelo") }
                vm.connectionMessage?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
            }

            Section("Modelo de lenguaje") {
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    SegmentedButton(d.provider == Provider.OLLAMA, { d = d.copy(provider = Provider.OLLAMA) }, SegmentedButtonDefaults.itemShape(0, 2)) { Text("Ollama local") }
                    SegmentedButton(d.provider == Provider.CLAUDE, { d = d.copy(provider = Provider.CLAUDE) }, SegmentedButtonDefaults.itemShape(1, 2)) { Text("Clave de API") }
                }
                when (d.provider) {
                    Provider.OLLAMA -> {
                        Field(d.ollamaHost, "Dirección de Ollama", KeyboardType.Uri) { d = d.copy(ollamaHost = it) }
                        Field(d.ollamaModel, "Modelo") { d = d.copy(ollamaModel = it) }
                        Text(
                            "La dirección la usa el servidor, no el móvil: si Ollama corre en el mismo PC que el servidor, deja http://localhost:11434. " +
                                "Sin coste de API; con modelos pequeños habrá más afirmaciones omitidas.",
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    Provider.CLAUDE -> {
                        OutlinedTextField(
                            d.claudeApiKey, { d = d.copy(claudeApiKey = it) }, Modifier.fillMaxWidth(),
                            label = { Text("Clave de API de Anthropic") },
                            supportingText = { Text("Vacía = usa la clave configurada en el servidor") },
                            singleLine = true,
                            visualTransformation = if (showKey) VisualTransformation.None else PasswordVisualTransformation(),
                            trailingIcon = { TextButton({ showKey = !showKey }) { Text(if (showKey) "Ocultar" else "Mostrar") } },
                        )
                        Field(d.claudeModel, "Modelo") { d = d.copy(claudeModel = it) }
                        Text("Cada consulta consume tokens de tu cuenta.", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }

            Section("Privacidad e historial") {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Guardar historial en este móvil", Modifier.weight(1f))
                    Switch(d.saveHistory, { d = d.copy(saveHistory = it) })
                }
                Text(
                    "El historial se guarda solo en este móvil, sin copia de seguridad ni transferencia a otros dispositivos. " +
                        "Las preguntas se guardan ya filtradas: el servidor oculta DNI/NIE, correos, teléfonos, fechas completas, " +
                        "nº de historia y nombres tras «paciente», «Sr./Sra.», «D./Dña.». Es un filtro heurístico: " +
                        "no detecta nombres escritos sin esos indicadores. Evita escribir datos de pacientes.",
                    style = MaterialTheme.typography.bodySmall,
                )
                OutlinedButton({ confirmDelete = true }, enabled = vm.conversations.isNotEmpty()) { Text("Borrar todo el historial") }
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button({ vm.saveSettings(d); d = vm.settings }, enabled = dirty) { Text("Guardar") }
                TextButton({ d = vm.settings }, enabled = dirty) { Text("Descartar") }
            }
        }
    }
}

@Composable
private fun DeleteHistoryDialog(onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("¿Borrar todo el historial?") },
        text = { Text("Se eliminarán todas las conversaciones guardadas en este móvil. No se puede deshacer.") },
        confirmButton = { TextButton(onConfirm) { Text("Borrar") } },
        dismissButton = { TextButton(onDismiss) { Text("Cancelar") } },
    )
}

@Composable
private fun Section(title: String, content: @Composable ColumnScope.() -> Unit) {
    ElevatedCard(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            content()
        }
    }
}

@Composable
private fun Field(value: String, label: String, type: KeyboardType = KeyboardType.Text, secret: Boolean = false, onChange: (String) -> Unit) {
    OutlinedTextField(
        value, onChange, Modifier.fillMaxWidth(), label = { Text(label) }, singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = if (secret) KeyboardType.Password else type),
        visualTransformation = if (secret) PasswordVisualTransformation() else VisualTransformation.None,
    )
}
