package com.evidencia.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { EvidenciaTheme { App() } }
    }
}

private enum class Screen { HOME, SETTINGS, HISTORY }

@Composable
fun App(vm: AppViewModel = viewModel()) {
    var screen by rememberSaveable { mutableStateOf(Screen.HOME) }
    BackHandler(enabled = screen != Screen.HOME) { screen = Screen.HOME }
    when (screen) {
        Screen.HOME -> HomeScreen(vm, onOpenSettings = { screen = Screen.SETTINGS }, onOpenHistory = { screen = Screen.HISTORY })
        Screen.SETTINGS -> SettingsScreen(vm) { screen = Screen.HOME }
        Screen.HISTORY -> HistoryScreen(vm, onBack = { screen = Screen.HOME }, onOpened = { screen = Screen.HOME })
    }
}
