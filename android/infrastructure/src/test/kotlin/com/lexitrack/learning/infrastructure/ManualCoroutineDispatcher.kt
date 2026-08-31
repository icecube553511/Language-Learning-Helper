package com.lexitrack.learning.infrastructure

import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread
import kotlin.coroutines.CoroutineContext
import kotlinx.coroutines.CoroutineDispatcher

internal class ManualCoroutineDispatcher : CoroutineDispatcher() {
    private val tasks = LinkedBlockingQueue<Runnable>()

    override fun dispatch(context: CoroutineContext, block: Runnable) {
        tasks.add(block)
    }

    fun runNextOnWorker() {
        val task = checkNotNull(tasks.poll(5, TimeUnit.SECONDS)) {
            "Timed out waiting for a dispatched persistence task"
        }
        val failure = AtomicReference<Throwable?>()
        val worker = thread(start = true, name = "repository-test-io") {
            try {
                task.run()
            } catch (error: Throwable) {
                failure.set(error)
            }
        }
        worker.join(5_000)
        check(!worker.isAlive) { "Persistence task did not finish" }
        failure.get()?.let { throw it }
    }
}
