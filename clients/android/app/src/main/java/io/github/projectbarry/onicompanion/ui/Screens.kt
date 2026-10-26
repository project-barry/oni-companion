package io.github.projectbarry.onicompanion.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.projectbarry.onicompanion.discovery.Entry
import io.github.projectbarry.onicompanion.discovery.Trust
import io.github.projectbarry.onicompanion.net.Fingerprint
import io.github.projectbarry.onicompanion.store.Pairing

@Composable
fun RootScreen(vm: MainViewModel, onScan: () -> Unit, onPickFolder: () -> Unit = {}, hasSecondDisplay: Boolean = false) {
    val conf = LocalConfiguration.current
    Fit.window(conf.screenWidthDp, conf.screenHeightDp)
    key(conf.screenWidthDp, conf.screenHeightDp) { RootContent(vm, onScan, onPickFolder, hasSecondDisplay) }
}

@Composable
private fun RootContent(vm: MainViewModel, onScan: () -> Unit, onPickFolder: () -> Unit, hasSecondDisplay: Boolean) {
    Surface(Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Box(Modifier.safeDrawingPadding().then(if (vm.route is Route.Service) Modifier else Modifier.padding(horizontal = 16.dp))) {
            when (val r = vm.route) {
                Route.Devices -> DevicesScreen(vm, onScan, hasSecondDisplay)
                is Route.LocalSetup -> LocalSetupScreen(r, vm, onPickFolder)
                is Route.LocalWaiting -> LocalWaitingScreen(r, vm)
                is Route.Manual -> ManualScreen(r, vm)
                is Route.Confirm -> ConfirmScreen(r, vm)
                is Route.Working -> Column(Modifier.fillMaxSize(), Arrangement.Center, Alignment.CenterHorizontally) {
                    CircularProgressIndicator(); Spacer(Modifier.height(16.dp)); Text(r.text)
                }
                is Route.Message -> MessageScreen(r, vm)
                is Route.Service -> ServiceScreen(r, vm)
            }
        }
    }
}

@Composable
private fun Title(text: String) =
    Text(text, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 20.dp, bottom = 8.dp))

@Composable
private fun DevicesScreen(vm: MainViewModel, onScan: () -> Unit, hasSecondDisplay: Boolean) {
    val found by vm.discovery.entries.collectAsState()
    LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item { Title("ONI Companion") }
        item { LocalCard(vm, hasSecondDisplay) }
        item {
            Text("Open Connect a phone on the gaming device (in the game's pause menu), then scan its QR code.",
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                Button(onClick = onScan, modifier = Modifier.weight(1f)) { Text("Scan QR code") }
                OutlinedButton(onClick = { vm.go(Route.Manual()) }, modifier = Modifier.weight(1f)) { Text("Type address") }
            }
        }
        item { Text("Paired", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 12.dp)) }
        if (vm.pairings.isEmpty()) item { Text("No gaming device paired yet.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        items(vm.pairings, key = { it.fingerprint }) { p -> PairedRow(p, onOpen = { vm.open(p) }, onForget = { vm.forget(p) }) }
        item { Text("Found nearby", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 12.dp)) }
        if (found.isEmpty()) item { Text("Looking for gaming devices on this network. They appear while Connect a phone is on.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        items(found, key = { it.announced.key }) { e -> FoundRow(e, vm) }
    }
}

@Composable
private fun Card(modifier: Modifier = Modifier, content: @Composable () -> Unit) =
    Surface(modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surfaceVariant) {
        Box(Modifier.padding(14.dp)) { content() }
    }

@Composable
private fun PairedRow(p: Pairing, onOpen: () -> Unit, onForget: () -> Unit) {
    var ask by remember { mutableStateOf(false) }
    Card(Modifier.clickable(onClick = onOpen)) {
        Column {
            Text(p.title, style = MaterialTheme.typography.titleMedium)
            Text("Paired", color = MaterialTheme.colorScheme.primary)
            if (ask) {
                Text("Forget this device on this phone? It stays in the gaming device's list until you remove it there.")
                Row { TextButton(onClick = onForget) { Text("Forget") }; TextButton(onClick = { ask = false }) { Text("Cancel") } }
            } else TextButton(onClick = { ask = true }) { Text("Forget") }
        }
    }
}

@Composable
private fun FoundRow(e: Entry, vm: MainViewModel) {
    val (label, color) = when (e.trust) {
        Trust.Checking -> "Checking…" to MaterialTheme.colorScheme.onSurfaceVariant
        Trust.Paired -> "Paired" to MaterialTheme.colorScheme.primary
        Trust.New -> "New" to MaterialTheme.colorScheme.onSurface
        Trust.CantVerify -> "Can't verify this device" to MaterialTheme.colorScheme.error
        Trust.Unreachable -> "Not reachable" to MaterialTheme.colorScheme.onSurfaceVariant
    }
    Card(Modifier.clickable(enabled = e.trust == Trust.Paired || e.trust == Trust.New) {
        if (e.pairing != null) vm.open(e.pairing) else vm.go(Route.Manual("${e.announced.host}:${e.announced.port}", ""))
    }) {
        Column {
            Text(e.title, style = MaterialTheme.typography.titleMedium)
            Text(label, color = color)
            if (e.trust == Trust.New) Text("Tap, then type the code from the gaming device.", color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (e.needsUpdate) Text("Update the app to pair with this device.", color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun ManualScreen(r: Route.Manual, vm: MainViewModel) {
    var host by rememberSaveable(r) { mutableStateOf(r.host) }
    var code by rememberSaveable(r) { mutableStateOf(r.code) }
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Title("Type address")
        Text("Both are shown in the Connect a phone window on the gaming device.", color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedTextField(host, { host = it }, label = { Text("Address, e.g. 192.168.1.20:47615") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), modifier = Modifier.fillMaxWidth())
        OutlinedTextField(code, { code = it.uppercase() }, label = { Text("Code, e.g. ABCD-EFGH") }, singleLine = true,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Characters), modifier = Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { vm.checkTyped(host, code) }, enabled = host.isNotBlank() && code.replace("-", "").length == 8) { Text("Next") }
            TextButton(onClick = vm::home) { Text("Cancel") }
        }
    }
}

@Composable
private fun ConfirmScreen(r: Route.Confirm, vm: MainViewModel) {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Title("Is this your device?")
        Text("The Connect a phone window on the gaming device shows this name and these characters. Pair only if they are the same.")
        Card {
            Column {
                Text(r.name ?: "(no name)", style = MaterialTheme.typography.headlineSmall)
                Text(Fingerprint.tag(r.fingerprint), style = MaterialTheme.typography.displayMedium, fontWeight = FontWeight.Bold,
                    color = MaterialTheme.colorScheme.primary)
                Text(r.fingerprint.take(16).chunked(4).joinToString(" ").uppercase(), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { vm.confirmTyped(r) }) { Text("They match, pair") }
            OutlinedButton(onClick = vm::home) { Text("They differ") }
        }
    }
}

@Composable
private fun MessageScreen(r: Route.Message, vm: MainViewModel) {
    Column(Modifier.fillMaxSize(), Arrangement.Center, Alignment.CenterHorizontally) {
        Text(r.title ?: if (r.cantVerify) "Can't verify this device" else "Couldn't pair", style = MaterialTheme.typography.headlineSmall,
            color = MaterialTheme.colorScheme.error)
        Spacer(Modifier.height(8.dp))
        Text(r.text)
        Spacer(Modifier.height(16.dp))
        Button(onClick = vm::home) { Text("OK") }
    }
}
