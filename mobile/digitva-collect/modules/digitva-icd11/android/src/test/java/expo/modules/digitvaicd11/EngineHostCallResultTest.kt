package expo.modules.digitvaicd11

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The result map of one engine call (EngineHost.call without the Android parts). */
class EngineHostCallResultTest {
  private fun result(initialised: Boolean = true, op: String = "search", input: String = """{"q":"x"}""", reply: ByteArray? = "{}".toByteArray(), status: Int = 200) =
    callResult(initialised, op, input) { _, _, s ->
      s[0] = status
      reply
    }

  @Test fun successCarriesStatusTextAndTime() {
    val map = result(reply = """{"a":"नमोनिया"}""".toByteArray(Charsets.UTF_8), status = 200)
    assertEquals(true, map["ok"])
    assertEquals(200, map["status"])
    assertEquals("""{"a":"नमोनिया"}""", map["text"]) // decoded as UTF-8
    assertTrue((map["nativeMs"] as Double) >= 0.0)
    assertEquals(setOf("ok", "status", "text", "nativeMs"), map.keys)
  }

  @Test fun everyStatusFrom200To299IsASuccess() {
    for (status in listOf(200, 201, 204, 299)) assertEquals(status, result(status = status)["status"])
    for (status in listOf(199, 300, 400, 404, 500, 503)) assertEquals("engine_status", result(status = status)["error"])
  }

  @Test fun theOpAndInputReachTheEngineUnchanged() {
    val seen = mutableListOf<String>()
    callResult(true, "foundation_entity", """{"id":"1"}""") { op, json, _ ->
      seen += op
      seen += json
      null
    }
    assertEquals(listOf("foundation_entity", """{"id":"1"}"""), seen)
  }

  @Test fun aFailedCallDropsTheBodyAndKeepsTheStatus() {
    val map = result(reply = """{"error":"echo of the certificate text"}""".toByteArray(), status = 400)
    assertEquals(false, map["ok"])
    assertEquals("engine_status", map["error"])
    assertEquals(400, map["status"])
    assertFalse(map.containsKey("text"))
    assertTrue(map.containsKey("nativeMs"))
  }

  @Test fun noBytesIsEngineStatusEvenWhenTheStatusLooksFine() {
    val map = result(reply = null, status = 200)
    assertEquals("engine_status", map["error"])
    assertEquals(200, map["status"])
    assertFalse(map.containsKey("text"))
  }

  @Test fun noBytesAndNoStatusReportsStatusZero() {
    val map = callResult(true, "search", "{}") { _, _, _ -> null }
    assertEquals("engine_status", map["error"])
    assertEquals(0, map["status"])
  }

  @Test fun beforeInitTheEngineIsNotCalled() {
    var called = false
    val map = callResult(false, "search", "{}") { _, _, _ ->
      called = true
      null
    }
    assertFalse(called)
    assertEquals(mapOf("ok" to false, "error" to "not_initialized", "status" to 503, "nativeMs" to 0.0), map)
  }

  @Test fun anOpNameOfTheWrongShapeIsBadOpEvenBeforeInit() {
    for (op in listOf("", "Search", "search1", "bad op", "a-b", "../x", "x".repeat(33), "search\n")) {
      for (initialised in listOf(true, false)) {
        var called = false
        val map = callResult(initialised, op, "{}") { _, _, _ ->
          called = true
          null
        }
        assertFalse("op '$op' reached the engine", called)
        assertEquals(mapOf("ok" to false, "error" to "bad_op", "status" to 0, "nativeMs" to 0.0), map)
      }
    }
  }

  @Test fun anyWellShapedOpReachesTheEngineWhichDecidesIfItExists() {
    for (op in listOf("search", "foundation_entity", "a", "_", "x".repeat(32), "not_an_op")) {
      var called = false
      callResult(true, op, "{}") { _, _, _ ->
        called = true
        null
      }
      assertTrue("op '$op' was refused", called)
    }
  }
}
