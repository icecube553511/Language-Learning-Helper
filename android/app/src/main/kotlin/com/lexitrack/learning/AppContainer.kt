package com.lexitrack.learning

import android.content.Context
import com.lexitrack.learning.application.AppUseCases
import com.lexitrack.learning.application.BuildDashboardUseCase
import com.lexitrack.learning.application.BuildForecastUseCase
import com.lexitrack.learning.application.BuildReviewSessionUseCase
import com.lexitrack.learning.application.GetNextCardUseCase
import com.lexitrack.learning.application.GetReminderCardUseCase
import com.lexitrack.learning.application.ImportVocabularyUseCase
import com.lexitrack.learning.application.InitializeAppUseCase
import com.lexitrack.learning.application.RateWordUseCase
import com.lexitrack.learning.application.RateReviewWordUseCase
import com.lexitrack.learning.application.SearchVocabularyUseCase
import com.lexitrack.learning.application.UpdateFontScaleUseCase
import com.lexitrack.learning.application.UpdateReviewBatchSizeUseCase
import com.lexitrack.learning.application.UpdateReminderSettingsUseCase
import com.lexitrack.learning.application.UpdateReminderLevelsUseCase
import com.lexitrack.learning.application.UpdateStudyLevelsUseCase
import com.lexitrack.learning.application.UpdateReviewLevelsUseCase
import com.lexitrack.learning.application.UpdateStudyOrderUseCase
import com.lexitrack.learning.application.UpdateVocabularyLabelsUseCase
import com.lexitrack.learning.infrastructure.AndroidLearntWordsRepository
import com.lexitrack.learning.infrastructure.AndroidReviewRepository
import com.lexitrack.learning.infrastructure.AndroidSettingsRepository
import com.lexitrack.learning.infrastructure.AndroidVocabularyRepository
import com.lexitrack.learning.infrastructure.SystemTimeProvider

class AppContainer(context: Context) {
    private val vocabulary = AndroidVocabularyRepository(context)
    private val reviews = AndroidReviewRepository(context)
    private val learntWords = AndroidLearntWordsRepository(context)
    private val settings = AndroidSettingsRepository(context)
    private val time = SystemTimeProvider()

    val useCases = AppUseCases(
        initialize = InitializeAppUseCase(vocabulary, reviews, learntWords),
        nextCard = GetNextCardUseCase(vocabulary, learntWords, settings),
        rateWord = RateWordUseCase(reviews, learntWords, time),
        startReviewSession = BuildReviewSessionUseCase(vocabulary, learntWords, settings),
        rateReviewWord = RateReviewWordUseCase(reviews, learntWords, time),
        search = SearchVocabularyUseCase(vocabulary),
        importVocabulary = ImportVocabularyUseCase(vocabulary),
        updateVocabularyLabels = UpdateVocabularyLabelsUseCase(vocabulary),
        updateFontScale = UpdateFontScaleUseCase(settings),
        updateReviewBatchSize = UpdateReviewBatchSizeUseCase(settings, learntWords),
        updateReminderSettings = UpdateReminderSettingsUseCase(settings),
        updateStudyOrder = UpdateStudyOrderUseCase(settings),
        updateStudyLevels = UpdateStudyLevelsUseCase(settings),
        updateReviewLevels = UpdateReviewLevelsUseCase(settings),
        updateReminderLevels = UpdateReminderLevelsUseCase(settings),
        reminderCard = GetReminderCardUseCase(vocabulary, reviews, settings, time),
        dashboard = BuildDashboardUseCase(vocabulary, reviews, learntWords, time),
        forecast = BuildForecastUseCase(vocabulary, reviews, time),
        words = vocabulary.words,
        catalogStatus = vocabulary.status,
        schedules = reviews.schedules,
        history = reviews.history,
        learntWords = learntWords.learntWords,
        settings = settings.settings,
    )
}
