package io.github.projectbarry.onicompanion

import io.github.projectbarry.onicompanion.session.Fatal
import io.github.projectbarry.onicompanion.session.FatalText
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FatalTextTest {
    @Test fun resetScreenOffersPairingWhenPaired() {
        for (f in listOf(Fatal.Unpaired, Fatal.CantVerify)) {
            val t = FatalText.of(f, paired = true)
            assertTrue(t.title.contains("reset"))
            assertTrue(t.title.contains("pair again"))
            assertTrue(t.pairAgain)
            assertFalse(FatalText.of(f, paired = false).pairAgain)
        }
    }

    @Test fun cantVerifyWarnsNotToPairBlindly() {
        assertTrue(FatalText.of(Fatal.CantVerify, true).text.contains("do not pair"))
    }

    @Test fun silenceBecomesAScreenOnlyAfterSeveralFailures() {
        assertFalse(FatalText.lost(connected = false, failures = 1, fatal = null))
        assertTrue(FatalText.lost(connected = false, failures = FatalText.LOST_AFTER_FAILURES, fatal = null))
        assertFalse(FatalText.lost(connected = true, failures = 9, fatal = null))
        assertFalse(FatalText.lost(connected = false, failures = 9, fatal = Fatal.Unpaired))   // the fatal screen wins
    }

    @Test fun headerWordsAreShortAndNeverCutMidWord() {
        assertEquals("No connection", FatalText.headerState(false, "Running"))
        assertEquals("Connecting...", FatalText.headerState(true, null))
        assertEquals("Colony running", FatalText.headerState(true, "Colony running"))
    }
}
