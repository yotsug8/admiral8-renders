import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.project_workspace import create
from tools.review_gate import mark_ready, sha256, validate


class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.guide = self.root / 'PROJECT_GUIDE.md'
        self.guide.write_text('<a id="rules"></a>\n# Rules\nCheck the whole video.\n', encoding='utf-8')
        self.work = self.root / 'work'
        self.work.mkdir()
        self.project = self.work / 'project.json'
        for name, body in [('video.mp4', b'video fixture'), ('scene.blend', b'scene fixture'),
                           ('review.txt', b'Full playback, light and contacts inspected; limits recorded.')]:
            (self.work / name).write_bytes(body)
        self.data = {
            'status': 'review_in_progress',
            'requirements': [{'id': 'motion', 'source': 'PROJECT_GUIDE.md#rules',
                              'criterion': 'Review full motion and frame transitions',
                              'status': 'verified', 'method': 'Full normal-speed playback plus transition frames',
                              'evidence_files': [self.record('review.txt')]}],
            'review': {'guide_sha256': sha256(self.guide), 'reviewed_at': '2026-11-15T00:10:00+03:00',
                       'coverage_note': 'Reviewed the current guide and applicability to this silent scene.',
                       'artifacts': [dict(self.record('video.mp4'), role='video'),
                                     dict(self.record('scene.blend'), role='source')]},
        }
        self.write()

    def record(self, name):
        return {'path': name, 'sha256': sha256(self.work / name)}

    def write(self):
        self.project.write_text(json.dumps(self.data), encoding='utf-8')

    def errors(self):
        self.write()
        return validate(self.project, self.guide)

    def test_complete_current_review_passes_without_changing_project(self):
        before = self.project.read_bytes()
        self.assertEqual(validate(self.project, self.guide), [])
        self.assertEqual(self.project.read_bytes(), before)

    def test_changed_guide_reopens_review(self):
        self.guide.write_text(self.guide.read_text() + '\nNew requirement.\n')
        self.assertTrue(any('guide SHA-256' in e for e in self.errors()))

    def test_changed_video_scene_or_evidence_is_rejected(self):
        for name in ['video.mp4', 'scene.blend', 'review.txt']:
            with self.subTest(file=name):
                target = self.work / name
                original = target.read_bytes()
                target.write_bytes(original + b'new revision')
                self.assertTrue(any('stale or changed file' in e for e in self.errors()))
                target.write_bytes(original)

    def test_missing_evidence_is_rejected(self):
        (self.work / 'review.txt').unlink()
        self.assertTrue(any('cannot read' in e for e in self.errors()))

    def test_pending_or_tested_statuses_do_not_mean_ready(self):
        for status in ['tested', 'not_tested', 'blocked', 'implemented', 'experimental', None]:
            with self.subTest(status=status):
                self.data['requirements'][0]['status'] = status
                self.assertTrue(any('unresolved status' in e for e in self.errors()))

    def test_empty_checklist_and_duplicate_ids_are_rejected(self):
        criterion = self.data['requirements'][0]
        self.data['requirements'] = []
        self.assertTrue(any('nonempty applicability checklist' in e for e in self.errors()))
        self.data['requirements'] = [criterion, copy.deepcopy(criterion)]
        self.assertTrue(any('unique' in e for e in self.errors()))

    def test_not_applicable_requires_reason(self):
        requirement = self.data['requirements'][0]
        requirement['status'] = 'not_applicable'
        self.assertTrue(any('requires a reason' in e for e in self.errors()))
        requirement['reason'] = 'This shot contains no articulated actor or moving camera.'
        self.assertEqual(self.errors(), [])

    def test_method_evidence_and_guide_anchor_are_required(self):
        requirement = self.data['requirements'][0]
        requirement.update(method='', evidence_files=[], source='PROJECT_GUIDE.md#missing')
        errors = self.errors()
        for phrase in ['verification method', 'hashed evidence_files', 'existing PROJECT_GUIDE.md anchor']:
            self.assertTrue(any(phrase in e for e in errors), errors)

    def test_both_final_video_and_authored_input_are_required(self):
        self.data['review']['artifacts'] = self.data['review']['artifacts'][:1]
        self.assertTrue(any('both video and source' in e for e in self.errors()))

    def test_invalid_records_and_paths_fail_without_traceback(self):
        for value in [None, [], {'path': '../outside', 'sha256': '0' * 64},
                      {'path': 'C:/outside', 'sha256': '0' * 64},
                      {'path': 'review.txt', 'sha256': 'wrong'}]:
            with self.subTest(value=value):
                self.data['requirements'][0]['evidence_files'] = [value]
                self.assertTrue(self.errors())

    def test_new_workspace_is_not_ready(self):
        work = create(self.root, 'new-work', 'Create a video')
        errors = validate(work / 'project.json', self.guide)
        self.assertTrue(any('nonempty applicability checklist' in e for e in errors))
        self.assertTrue(any('artifacts' in e for e in errors))

    def test_mark_ready_failure_does_not_change_project(self):
        self.data['requirements'][0]['status'] = 'not_tested'
        self.write()
        before = self.project.read_bytes()
        self.assertTrue(mark_ready(self.project, self.guide))
        self.assertEqual(self.project.read_bytes(), before)
        self.assertEqual(list(self.work.glob('.review-*.tmp')), [])

    def test_explicit_mark_ready_updates_only_status(self):
        self.assertEqual(mark_ready(self.project, self.guide), [])
        expected = copy.deepcopy(self.data)
        expected['status'] = 'ready_for_user_review'
        self.assertEqual(json.loads(self.project.read_text()), expected)
        self.assertEqual(list(self.work.glob('.review-*.tmp')), [])

    def test_failed_atomic_write_preserves_original(self):
        before = self.project.read_bytes()
        with patch('tools.review_gate.os.replace', side_effect=PermissionError('locked')):
            self.assertTrue(mark_ready(self.project, self.guide))
        self.assertEqual(self.project.read_bytes(), before)
        self.assertEqual(list(self.work.glob('.review-*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
