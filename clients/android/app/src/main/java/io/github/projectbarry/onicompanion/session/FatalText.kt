package io.github.projectbarry.onicompanion.session

/** What the full-screen problem message says (no Compose here, so it is unit-tested). */
data class ProblemText(val title: String, val text: String, val pairAgain: Boolean)

object FatalText {
    /** [paired] = this view belongs to a saved pairing (so it can be forgotten and paired again). */
    fun of(f: Fatal, paired: Boolean): ProblemText = when (f) {
        Fatal.Unpaired -> ProblemText(
            "This device was reset: pair again",
            "The gaming device no longer knows this phone. It was removed there, or the device was reset. " +
                "Open Connect a phone on the gaming device and pair again with a new code.",
            paired,
        )
        Fatal.CantVerify -> ProblemText(
            "This device was reset: pair again",
            "The device at this address is not the one you paired with. It was most likely reset and has a new identity. " +
                "If you did not reset it, do not pair: nothing was sent to it.",
            paired,
        )
    }

    /** The service has been silent this long (failed attempts in a row) before the phone says so on a full screen. */
    const val LOST_AFTER_FAILURES = 3

    fun lost(connected: Boolean, failures: Int, fatal: Fatal?) = fatal == null && !connected && failures >= LOST_AFTER_FAILURES

    const val LOST_TITLE = "No answer from the gaming device"
    const val LOST_TEXT = "It may be off, the game may be closed, Connect a phone may be switched off, or the device was reset " +
        "(a reset also switches Connect a phone off). The phone keeps trying. If it was reset, forget it here and pair again."

    /** Header words next to the state dot; short enough to wrap at a space, never to cut a word. */
    fun headerState(connected: Boolean, gameLabel: String?): String =
        if (!connected) "No connection" else gameLabel ?: "Connecting..."
}
