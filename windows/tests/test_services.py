from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from application.services import LearningService
from domain.models import ExampleSentence, VocabularyEntry
from infrastructure.repository import JsonLearningRepository


class LearningServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        entry = VocabularyEntry.create("focus", "专注", [
            ExampleSentence("Focus on the task.", "专注于任务。"),
            ExampleSentence("The camera can focus quickly.", "相机可以快速对焦。"),
            ExampleSentence("Her focus improved.", "她的专注力提高了。"),
        ])
        self.repo = JsonLearningRepository(Path(self.temp.name), [entry])
        self.service = LearningService(self.repo)

    def test_study_rate_and_dashboard(self):
        card = self.service.next_card(now_utc=1000)
        self.assertEqual(card.word, "focus")
        state = self.service.rate_card(card.word_id, "good", reviewed_at_utc=1000)
        self.assertEqual(state.interval_days, 3)
        snapshot = self.service.dashboard(now_utc=1001)
        self.assertEqual(snapshot.total_words, 1)
        self.assertEqual(snapshot.new_words, 0)

    def test_font_scale_is_bounded(self):
        self.assertEqual(self.service.set_font_scale(2), 1.4)
        self.assertEqual(self.service.set_font_scale(0), 0.9)


if __name__ == "__main__":
    unittest.main()
