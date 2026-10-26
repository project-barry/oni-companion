package io.github.projectbarry.onicompanion.ui

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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/** Steps per emulator app. Menu names are not claimed for apps whose menus were not read (docs/android-dual-screen.md). */
fun driveSteps(emulator: String?): List<String> {
    val drive = "Make one Wine drive (D: to Z:) point at the Android folder that contains ONICompanion."
    val where = when (emulator) {
        "Winlator" -> "Winlator: open the container's settings and find Drives (it maps D: to the Downloads folder by default). Point a drive at the folder that contains ONICompanion."
        "GameNative" -> "GameNative: open the game's container settings and find the drives setting. $drive"
        "GameHub" -> "GameHub: open the game's settings and look for storage or drive options. $drive"
        else -> "In your emulator app: $drive"
    }
    return listOf(
        "Press Choose folder below. In the picker, open the menu, choose New folder, name it ONICompanion and press Use this folder. It must be at the top of the internal storage.",
        where,
        "Install the ONI Companion Link mod in the game and turn it on. Start ONI and load a colony.",
        "This screen continues by itself when the game writes its first files.",
    )
}

@Composable
fun LocalSetupScreen(r: Route.LocalSetup, vm: MainViewModel, onPick: () -> Unit) {
    LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item { Text("This device", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold, modifier = Modifier.padding(top = 20.dp)) }
        item { Text("Show the colony here while ONI runs in an emulator app on this device. Nothing leaves the device.", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        item { Text("Which emulator app runs ONI?", style = MaterialTheme.typography.titleMedium) }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                vm.emulators.forEach { n -> FilterChip(selected = r.emulator == n, onClick = { vm.chooseEmulator(n) }, label = { Text(n) }) }
            }
        }
        if (r.emulator != null) {
            driveSteps(r.emulator).forEachIndexed { i, t -> item { Text("${i + 1}. $t") } }
            item { Button(onClick = onPick) { Text("Choose folder") } }
        }
        item { TextButton(onClick = vm::home) { Text("Cancel") } }
    }
}

@Composable
fun LocalWaitingScreen(r: Route.LocalWaiting, vm: MainViewModel) {
    LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Row(Modifier.padding(top = 20.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                CircularProgressIndicator(); Text("Waiting for the game", style = MaterialTheme.typography.headlineSmall)
            }
        }
        item { Text("The folder is ready. Start ONI with the mod turned on. If this stays here, check the steps:", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        driveSteps(r.emulator).drop(1).forEachIndexed { i, t -> item { Text("${i + 1}. $t") } }
        item { OutlinedButton(onClick = vm::refreshLocal) { Text("Look again") } }
        item { TextButton(onClick = vm::home) { Text("Cancel") } }
    }
}

/** The "This device" card on the Devices screen, plus the bottom-screen switch when a second display exists. */
@Composable
fun LocalCard(vm: MainViewModel, hasSecondDisplay: Boolean) {
    Surface(Modifier.fillMaxWidth(), shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surfaceVariant) {
        Column(Modifier.padding(14.dp)) {
            Text("This device", style = MaterialTheme.typography.titleMedium)
            when (vm.localState) {
                LocalState.None -> {
                    Text("ONI runs in an emulator app on this device.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    TextButton(onClick = { vm.startLocalSetup() }) { Text("Set up") }
                }
                LocalState.Granted -> {
                    Text("Set up. The game is not writing now; opening shows its last state.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Row { TextButton(onClick = { vm.openLocal() }) { Text("Open") }; TextButton(onClick = { vm.startLocalSetup() }) { Text("Set up again") } }
                }
                LocalState.Fresh -> {
                    Text("The game is running.", color = MaterialTheme.colorScheme.primary)
                    TextButton(onClick = { vm.openLocal() }) { Text("Open") }
                }
            }
            if (hasSecondDisplay) Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text("Open on the bottom screen", Modifier.weight(1f))
                Switch(checked = vm.bottomScreen, onCheckedChange = vm::changeBottomScreen)
            }
        }
    }
}
