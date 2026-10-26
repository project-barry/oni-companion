package io.github.projectbarry.onicompanion

import android.content.pm.ApplicationInfo
import android.os.Bundle
import androidx.activity.ComponentActivity
import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.activity.result.contract.ActivityResultContracts
import io.github.projectbarry.onicompanion.local.Displays
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import io.github.projectbarry.onicompanion.ui.MainViewModel
import io.github.projectbarry.onicompanion.ui.OniTheme
import io.github.projectbarry.onicompanion.ui.Route
import io.github.projectbarry.onicompanion.ui.RootScreen

class MainActivity : ComponentActivity() {
    private val vm: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Dual-screen handheld: open on the bottom screen once (plan 4.2).
        if (savedInstanceState == null && Displays.moveToSecondary(this, (application as OniApp).localStore.bottomScreen)) { finish(); return }
        if (savedInstanceState == null) handleDebugIntent()
        setContent {
            OniTheme {
                val scan = rememberLauncherForActivityResult(ScanContract()) { r -> r.contents?.let(vm::onQr) }
                val pick = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { r ->
                    vm.onTreePicked(if (r.resultCode == RESULT_OK) r.data?.data else null, r.data?.flags ?: 0)
                }
                BackHandler(enabled = vm.route !is Route.Devices) { vm.home() }
                RootScreen(vm, onPickFolder = {
                    pick.launch(Intent(Intent.ACTION_OPEN_DOCUMENT_TREE).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION or Intent.FLAG_GRANT_PREFIX_URI_PERMISSION))
                }, hasSecondDisplay = Displays.secondary(this@MainActivity) != null, onScan = {
                    scan.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE)
                        .setPrompt("Scan the QR code in Connect a phone").setBeepEnabled(false).setOrientationLocked(false))
                })
            }
        }
    }

    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); handleDebugIntent() }

    override fun onStart() { super.onStart(); vm.startDiscovery(); vm.appVisible(true) }
    override fun onStop() { vm.stopDiscovery(); vm.appVisible(false); super.onStop() }

    /** Debug builds only: drive the app from adb without typing (see clients/android/README.md). */
    private fun handleDebugIntent() {
        if (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE == 0) return
        intent.getStringExtra("dev_loopback")?.split(":")?.let { if (it.size == 2) it[0].toIntOrNull()?.let { p -> vm.openLoopback(p, it[1]) } }
        intent.getStringExtra("dev_bottom")?.let { vm.changeBottomScreen(it == "1") }
        intent.getStringExtra("dev_local_call")?.let { vm.debugLocalCall(it) }
        intent.getStringExtra("dev_manual")?.let { t ->
            val i = t.lastIndexOf(':')
            if (i > 0) vm.go(Route.Manual(t.substring(0, i), t.substring(i + 1)))
        }
    }
}
