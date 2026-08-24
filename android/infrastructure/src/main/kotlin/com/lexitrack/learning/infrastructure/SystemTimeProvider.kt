package com.lexitrack.learning.infrastructure

import com.lexitrack.learning.application.TimeProvider
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

class SystemTimeProvider(
    private val zoneId: ZoneId = ZoneId.systemDefault(),
) : TimeProvider {
    override fun nowUtcSeconds(): Double = System.currentTimeMillis() / 1000.0

    override fun localDate(epochSeconds: Double): LocalDate = Instant
        .ofEpochMilli((epochSeconds * 1000.0).toLong())
        .atZone(zoneId)
        .toLocalDate()
}
