package com.evidencia.app

import android.content.Context

enum class Provider { CLAUDE, OLLAMA }

data class AppSettings(
    val backendUrl: String = "http://10.0.2.2:8000", // emulador -> PC anfitrión
    val appToken: String = "",
    val provider: Provider = Provider.OLLAMA,
    val claudeApiKey: String = "", // vacío = usa la clave del servidor
    val claudeModel: String = "claude-opus-5-5",
    val ollamaHost: String = "http://localhost:11434", // relativo al SERVIDOR, no al móvil
    val ollamaModel: String = "qwen2.5:7b-instruct",
    val saveHistory: Boolean = true, // historial solo en este móvil
)

/** Persistencia local. TODO: la clave de API va en texto plano (privado a la app); migrar a Keystore. */
class SettingsStore(context: Context) {
    private val p = context.getSharedPreferences("settings", Context.MODE_PRIVATE)

    fun load(): AppSettings {
        val d = AppSettings()
        return AppSettings(
            backendUrl = p.getString("backendUrl", d.backendUrl)!!,
            appToken = p.getString("appToken", d.appToken)!!,
            provider = runCatching { Provider.valueOf(p.getString("provider", d.provider.name)!!) }.getOrDefault(d.provider),
            claudeApiKey = p.getString("claudeApiKey", d.claudeApiKey)!!,
            claudeModel = p.getString("claudeModel", d.claudeModel)!!,
            ollamaHost = p.getString("ollamaHost", d.ollamaHost)!!,
            ollamaModel = p.getString("ollamaModel", d.ollamaModel)!!,
            saveHistory = p.getBoolean("saveHistory", d.saveHistory),
        )
    }

    fun save(s: AppSettings) {
        p.edit()
            .putString("backendUrl", s.backendUrl.trim().trimEnd('/'))
            .putString("appToken", s.appToken.trim())
            .putString("provider", s.provider.name)
            .putString("claudeApiKey", s.claudeApiKey.trim())
            .putString("claudeModel", s.claudeModel.trim())
            .putString("ollamaHost", s.ollamaHost.trim())
            .putString("ollamaModel", s.ollamaModel.trim())
            .putBoolean("saveHistory", s.saveHistory)
            .apply()
    }
}
