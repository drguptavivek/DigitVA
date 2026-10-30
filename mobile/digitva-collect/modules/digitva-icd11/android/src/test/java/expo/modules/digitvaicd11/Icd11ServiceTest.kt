package expo.modules.digitvaicd11

import android.os.DeadObjectException
import android.os.TransactionTooLargeException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/** The service's Android-free parts: the reply bound, the send fallbacks, op-name validation and the job scheduler. */
class Icd11ServiceTest {
  private val cap = Icd11Service.MAX_TEXT_CHARS

  // --- boundReply: the 250,000-character cap ---

  private fun reply(text: String) = mapOf("ok" to true, "status" to 200, "text" to text, "nativeMs" to 1.5)

  @Test fun theCapIsTwoHundredFiftyThousandCharacters() {
    assertEquals(250_000, cap)
  }

  @Test fun aTextAtTheCapIsKept() {
    val map = reply("a".repeat(cap))
    assertSame(map, Icd11Service.boundReply(map))
  }

  @Test fun aTextOverTheCapBecomesTooLargeAndKeepsTheOtherEntries() {
    val bounded = Icd11Service.boundReply(reply("a".repeat(cap + 1)))
    assertEquals(false, bounded["ok"])
    assertEquals("too_large", bounded["error"])
    assertEquals(200, bounded["status"])
    assertEquals(1.5, bounded["nativeMs"])
    assertFalse(bounded.containsKey("text"))
  }

  @Test fun theCapCountsCharactersNotBytes() {
    // 250,000 three-byte characters are still within the cap; the Parcel stores UTF-16, 2 bytes each.
    val map = reply("न".repeat(cap))
    assertSame(map, Icd11Service.boundReply(map))
  }

  @Test fun onlyTheTextEntryIsCapped() {
    val map = mapOf("ok" to false, "error" to "x".repeat(cap + 1), "status" to 400)
    assertSame(map, Icd11Service.boundReply(map))
    assertSame(emptyMap<String, Any?>(), Icd11Service.boundReply(emptyMap()))
    val nonString = mapOf("ok" to true, "text" to null)
    assertSame(nonString, Icd11Service.boundReply(nonString))
  }

  // --- answerWith: native_error and the too_large fallback ---

  private class Sent {
    val maps = mutableListOf<Map<String, Any?>>()
  }

  @Test fun theWorkResultIsSentOnce() {
    val sent = Sent()
    Icd11Service.answerWith({ reply("{}") }) { sent.maps += it }
    assertEquals(listOf(reply("{}")), sent.maps)
  }

  @Test fun aThrowingWorkIsAnsweredNativeErrorWithNoMessage() {
    for (failure in listOf<Throwable>(RuntimeException("secret certificate text"), IllegalStateException(), OutOfMemoryError(), StackOverflowError())) {
      val sent = Sent()
      Icd11Service.answerWith({ throw failure }) { sent.maps += it }
      assertEquals(listOf(mapOf("ok" to false, "error" to "native_error")), sent.maps)
    }
  }

  @Test fun aTransactionTooLargeSendIsAnsweredTooLarge() {
    val sent = Sent()
    var attempts = 0
    Icd11Service.answerWith({ reply("{}") }) {
      attempts++
      if (attempts == 1) throw TransactionTooLargeException()
      sent.maps += it
    }
    assertEquals(2, attempts)
    assertEquals(listOf(mapOf("ok" to false, "error" to "too_large")), sent.maps)
  }

  @Test fun whenEvenTheTooLargeAnswerCannotBeSentNothingIsThrown() {
    var attempts = 0
    Icd11Service.answerWith({ reply("{}") }) {
      attempts++
      throw if (attempts == 1) TransactionTooLargeException() else DeadObjectException()
    }
    assertEquals(2, attempts)
  }

  @Test fun anyOtherSendFailureMeansNobodyIsWaitingAndIsNotRetried() {
    for (failure in listOf<Exception>(DeadObjectException(), IllegalStateException(), RuntimeException())) {
      var attempts = 0
      Icd11Service.answerWith({ reply("{}") }) {
        attempts++
        throw failure
      }
      assertEquals(1, attempts)
    }
  }

  // --- op-name validation (service, host and module share the rule) ---

  @Test fun opNamesAreLowerCaseWordsOfOneToThirtyTwoCharacters() {
    for (name in listOf("search", "codeinfo", "entity", "foundation_entity", "doris", "codedit", "a", "_", "x".repeat(32))) {
      assertTrue(name, Icd11Service.OP_NAME.matches(name))
    }
    for (name in listOf("", "Search", "search1", "bad op", "a-b", "../x", "x".repeat(33), "search\n", " search", "sëarch")) {
      assertFalse("'$name'", Icd11Service.OP_NAME.matches(name))
    }
  }

  @Test fun requestKindsAndPrioritiesAreTheDocumentedOnes() {
    assertEquals(listOf(0, 1, 5, 100), listOf(Icd11Service.OP_INIT, Icd11Service.OP_CALL, Icd11Service.OP_UPDATE, Icd11Service.WHAT_PROGRESS))
    assertTrue(Icd11Service.PRIORITY_INTERACTIVE < Icd11Service.PRIORITY_SETUP && Icd11Service.PRIORITY_SETUP < Icd11Service.PRIORITY_HOUSEKEEPING)
  }

  // --- JobScheduler: priority order and the init gate ---

  private fun drain(scheduler: JobScheduler, count: Int) = repeat(count) { scheduler.take().run() }

  @Test fun interactiveBeforeSetupBeforeHousekeepingAndFirstComeFirstServedWithinAPriority() {
    val scheduler = JobScheduler()
    val order = mutableListOf<String>()
    scheduler.submit(Icd11Service.PRIORITY_HOUSEKEEPING) { order += "housekeeping" }
    scheduler.submit(Icd11Service.PRIORITY_SETUP) { order += "setup" }
    scheduler.submit(Icd11Service.PRIORITY_INTERACTIVE) { order += "call 1" }
    scheduler.submit(Icd11Service.PRIORITY_SETUP) { order += "setup 2" }
    scheduler.submit(Icd11Service.PRIORITY_INTERACTIVE) { order += "call 2" }
    scheduler.submit(Icd11Service.PRIORITY_INTERACTIVE) { order += "call 3" }
    drain(scheduler, 6)
    assertEquals(listOf("call 1", "call 2", "call 3", "setup", "setup 2", "housekeeping"), order)
  }

  @Test fun aCallWithNoInitPendingIsQueuedAtOnce() {
    val scheduler = JobScheduler()
    val order = mutableListOf<String>()
    scheduler.submitCall { order += "call" }
    drain(scheduler, 1)
    assertEquals(listOf("call"), order)
  }

  @Test fun aCallSubmittedWhileAnInitIsPendingWaitsForTheInitToAnswer() {
    val scheduler = JobScheduler()
    val order = mutableListOf<String>()
    scheduler.submitInit { order += "init" }
    scheduler.submitCall { order += "call" }
    // Had the call been queued now, its priority (0) would run it before the init (1).
    scheduler.take().run()
    assertEquals(listOf("init"), order)
    scheduler.take().run()
    assertEquals(listOf("init", "call"), order)
  }

  @Test fun callsWaitingOnAnInitKeepTheirArrivalOrder() {
    val scheduler = JobScheduler()
    val order = mutableListOf<String>()
    scheduler.submitInit { order += "init" }
    for (n in 1..3) scheduler.submitCall { order += "call $n" }
    drain(scheduler, 4)
    assertEquals(listOf("init", "call 1", "call 2", "call 3"), order)
  }

  @Test fun withTwoInitsPendingCallsAreHeldUntilBothHaveAnswered() {
    val scheduler = JobScheduler()
    val order = mutableListOf<String>()
    scheduler.submitInit { order += "init 1" }
    scheduler.submitInit { order += "init 2" }
    scheduler.submitCall { order += "call" }
    scheduler.take().run()
    scheduler.take().run()
    assertEquals(listOf("init 1", "init 2"), order.take(2))
    scheduler.take().run()
    assertEquals(listOf("init 1", "init 2", "call"), order)
  }

  @Test fun aCallBeforeTheInitRequestRunsFirst() {
    val scheduler = JobScheduler()
    val order = mutableListOf<String>()
    scheduler.submitCall { order += "early call" }
    scheduler.submitInit { order += "init" }
    drain(scheduler, 2)
    assertEquals(listOf("early call", "init"), order)
  }

  @Test fun aCallAfterTheInitHasAnsweredIsNotHeld() {
    val scheduler = JobScheduler()
    val order = mutableListOf<String>()
    scheduler.submitInit { order += "init" }
    drain(scheduler, 1)
    scheduler.submitCall { order += "call" }
    drain(scheduler, 1)
    assertEquals(listOf("init", "call"), order)
  }

  @Test fun theGateOpensOnlyAfterTheInitTaskHasFinished() {
    val scheduler = JobScheduler()
    val order = mutableListOf<String>()
    scheduler.submitInit {
      // The task is still running: a call arriving now is still held.
      scheduler.submitCall { order += "call" }
      order += "init"
    }
    scheduler.take().run()
    assertEquals(listOf("init"), order)
    scheduler.take().run()
    assertEquals(listOf("init", "call"), order)
  }
}
