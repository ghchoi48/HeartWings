import unittest

from maeumnarae.views.counseling_content import clean_html, editor_html


class CounselingContentTests(unittest.TestCase):
    def test_legacy_markdown_and_html_reopen(self):
        html = editor_html('## 제목\n\n**상담**')
        self.assertIn('<h2>제목</h2>', html)
        self.assertIn('<strong>상담</strong>', html)
        self.assertEqual(editor_html(html, 'html'), html)

    def test_active_content_is_removed_and_formatting_preserved(self):
        html = clean_html('<script>alert(1)</script><div onclick="alert(1)" style="text-align: center"><b>내용</b></div>')
        self.assertNotIn('script', html)
        self.assertNotIn('onclick', html)
        self.assertNotIn('alert', html)
        self.assertIn('<b>내용</b>', html)
        self.assertIn('text-align', html)
