package expo.modules.digitvaicd11

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** The failed-init count that decides when a new engine process stops auto-starting (EngineHost.init). */
class EngineDataFailuresTest {
  @Test fun countsOnlyFailuresOnTheSameBuild() {
    assertEquals(2, EngineData.priorFailures(EngineData.failedRecord(2, 100L), 100L))
    assertEquals(0, EngineData.priorFailures(EngineData.failedRecord(5, 100L), 101L)) // app updated: fresh try
  }

  @Test fun otherStatesAndNoRecordCountZero() {
    assertEquals(0, EngineData.priorFailures(null, 100L))
    assertEquals(0, EngineData.priorFailures(JSONObject().put("state", "shipped"), 100L))
    assertEquals(0, EngineData.priorFailures(JSONObject().put("state", "attempt").put("failures", 3).put("build", 100L), 100L))
    assertEquals(0, EngineData.priorFailures(JSONObject().put("state", "failed"), 100L))
  }

  @Test fun aRecordSurvivesTheRoundTripThroughText() {
    val text = EngineData.failedRecord(3, 1_730_000_000_000L).toString()
    assertEquals(3, EngineData.priorFailures(JSONObject(text), 1_730_000_000_000L))
  }
}
