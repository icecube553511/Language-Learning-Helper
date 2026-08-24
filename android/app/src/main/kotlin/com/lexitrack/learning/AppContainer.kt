package com.lexitrack.learning

import android.content.Context
import com.lexitrack.learning.application.AppUseCases
import com.lexitrack.learning.application.BuildDashboardUseCase
import com.lexitrack.learning.application.BuildForecastUseCase
import com.lexitrack.learning.application.GetNextCardUseCase
import com.lexitrack.learning.application.ImportVocabularyUseCase
import com.lexitrack.learning.application.InitializeAppUseCase
import com.lexitrack.learning.application.RateWordUseCase
import com.lexitrack.learning.application.SearchVocabularyUseCase
import com.lexitrack.learning.application.UpdateFontScaleUseCase
import com.lexitrack.learning.infrastructure.AndroidReviewRepository
import com.lexitrack.learning.infrastructure.AndroidSettingsRepository
import com.lexitrack.learning.infrastructure.AndroidVocabularyRepository
import com.lexitrack.learning.infrastructure.SystemTimeProvider

class AppContainer(context: Context) {
    private val vocabulary = AndroidVocabularyRepository(context)
    private val reviews = AndroidReviewRepository(context)
    private val settings = AndroidSettingsRepository(context)
    private val time = SystemTimeProvider()

    val useCases = AppUseCases(
        initialize = InitializeAppUseCase(vocabulary),
        nextCard = GetNextCardUseCase(vocabulary, reviews, time),
        rateWord = RateWordUseCase(reviews, time),
        search = SearchVocabularyUseCase(vocabulary),
        importVocabulary = ImportVocabularyUseCase(vocabulary),
        updateFontScale = UpdateFontScaleUseCase(settings),
        dashboard = BuildDashboardUseCase(vocabulary, reviews, time),
        forecast = BuildForecastUseCase(vocabulary, reviews, time),
        words = vocabulary.words,
        catalogStatus = vocabulary.status,
        schedules = reviews.schedules,
        history = reviews.history,
        settings = settings.settings,
    )
}

