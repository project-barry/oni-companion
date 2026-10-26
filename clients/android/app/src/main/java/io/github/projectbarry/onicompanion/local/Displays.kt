package io.github.projectbarry.onicompanion.local

import android.app.Activity
import android.app.ActivityOptions
import android.content.Context
import android.content.Intent
import android.hardware.display.DisplayManager
import android.view.Display

/** Finding the second screen of a dual-screen handheld and opening the app there (plan 4.2). */
object Displays {
    const val EXTRA_PLACED = "on_secondary_display"

    /** First display that is on, not the default one and not private. Nothing is hard-coded: ids differ per device. */
    fun secondary(ctx: Context): Display? {
        val dm = ctx.getSystemService(Context.DISPLAY_SERVICE) as DisplayManager
        return dm.displays.firstOrNull {
            it.displayId != Display.DEFAULT_DISPLAY && it.state == Display.STATE_ON && (it.flags and Display.FLAG_PRIVATE) == 0
        }
    }

    /** Re-launch this activity on the second screen once. Returns true when it did (the caller finishes). */
    fun moveToSecondary(a: Activity, enabled: Boolean): Boolean {
        if (!enabled || a.intent.getBooleanExtra(EXTRA_PLACED, false)) return false
        @Suppress("DEPRECATION") val here = a.windowManager.defaultDisplay.displayId   // the display this activity is on
        val target = secondary(a) ?: return false
        if (here == target.displayId) return false
        val i = Intent(a.intent).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK)
            .putExtra(EXTRA_PLACED, true)
        val opts = ActivityOptions.makeBasic().setLaunchDisplayId(target.displayId)
        return try { a.startActivity(i, opts.toBundle()); true } catch (e: Exception) { false }
    }
}
