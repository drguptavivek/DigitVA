package expo.modules.digitvaicd11

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The release gate (digitva-xhz7): the engine process is stopped only with no request pending, queued or binding. */
class ReleaseIdleTest {
  @Test fun nothingInFlightIsIdle() = assertTrue(idle(0, 0, false))
  @Test fun aPendingRequestBlocksRelease() = assertFalse(idle(1, 0, false))
  @Test fun aQueuedRequestBlocksRelease() = assertFalse(idle(0, 1, false))
  @Test fun aBindingUnderWayBlocksRelease() = assertFalse(idle(0, 0, true))
}
