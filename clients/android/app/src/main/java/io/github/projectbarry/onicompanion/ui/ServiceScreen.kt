package io.github.projectbarry.onicompanion.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.projectbarry.onicompanion.session.FatalText

/** One connected gaming device: the full app view, or the message when it can't be used (unpaired / can't verify). */
@Composable
fun ServiceScreen(r: Route.Service, vm: MainViewModel) {
    val session = vm.session
    Box(Modifier.fillMaxSize()) {
        if (session != null) ServiceShell(session, onLeave = vm::home)
        else Column(Modifier.fillMaxSize(), Arrangement.Center, Alignment.CenterHorizontally) { CircularProgressIndicator() }
        val fatal = session?.fatal
        if (fatal != null) {
            val t = FatalText.of(fatal, r.pairing != null)
            Problem(t.title, t.text, if (t.pairAgain) "Pair again" else null, { r.pairing?.let(vm::pairAgain) }, vm)
        } else if (session != null && FatalText.lost(session.connected, session.failures, null)) {
            Problem(FatalText.LOST_TITLE, FatalText.LOST_TEXT, if (r.pairing != null) "Forget and pair again" else null, { r.pairing?.let(vm::pairAgain) }, vm)
        }
    }
}

@Composable
private fun Problem(title: String, text: String, pairLabel: String?, onPair: () -> Unit, vm: MainViewModel) {
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), Arrangement.Center, Alignment.CenterHorizontally) {
            Text(title, style = MaterialTheme.typography.headlineSmall, color = MaterialTheme.colorScheme.error)
            Spacer(Modifier.height(8.dp)); Text(text); Spacer(Modifier.height(16.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (pairLabel != null) Button(onClick = onPair) { Text(pairLabel) }
                if (pairLabel != null) OutlinedButton(onClick = vm::home) { Text("Back") } else Button(onClick = vm::home) { Text("Back") }
            }
        }
    }
}
