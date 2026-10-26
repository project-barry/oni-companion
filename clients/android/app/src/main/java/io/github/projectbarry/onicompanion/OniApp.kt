package io.github.projectbarry.onicompanion

import android.app.Application
import io.github.projectbarry.onicompanion.store.KeystoreBox
import io.github.projectbarry.onicompanion.store.PairingStore
import io.github.projectbarry.onicompanion.local.LocalStore
import java.io.File

class OniApp : Application() {
    val localStore: LocalStore by lazy { LocalStore(this) }
    val store: PairingStore by lazy { PairingStore(File(filesDir, "pairings.bin"), KeystoreBox.create()) }
}
