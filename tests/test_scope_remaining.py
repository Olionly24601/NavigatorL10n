import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestRemainingInterfaceMessages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.locales = {
            name: json.loads((ROOT / 'locales' / f'{name}.json').read_text(encoding='utf-8'))['messages']
            for name in ('zh_CN', 'ja_JP')
        }
        cls.versions = {
            version: json.loads((ROOT / 'patches' / f'{version}.json').read_text(encoding='utf-8'))
            for version in ('2.7.1', '2.7.4')
        }

    def test_splash_and_toolbox_status_have_rules_in_both_versions(self):
        required = {
            'status.preparing_interface', 'status.loading_user_info',
            'status.loading_bundled_metadata', 'status.verifying_toolbox',
        }
        for version, config in self.versions.items():
            ids = {rule['id'] for item in config['files'] for rule in item['rules']}
            with self.subTest(version=version):
                self.assertTrue(required <= ids)

    def test_version_specific_gaps_closed(self):
        expected = {'2.7.1': 'channels.collecting_progress',
                    '2.7.4': 'home.cancel_progress'}
        for version, rid in expected.items():
            ids = {rule['id'] for item in self.versions[version]['files'] for rule in item['rules']}
            self.assertIn(rid, ids)
        ids274 = {rule['id'] for item in self.versions['2.7.4']['files'] for rule in item['rules']}
        self.assertIn('cloud.signing_in_progress', ids274)

    def test_cloud_action_preserves_internal_href_and_html(self):
        for lang, messages in self.locales.items():
            text = messages['cloud.signing_in_progress']
            with self.subTest(language=lang):
                self.assertIn('href="navigator://cloud/cancel"', text)
                self.assertIn('<span ', text)
                self.assertIn('</span>', text)
                self.assertIn('</a>', text)

    def test_environment_open_with_menu_localized_in_both_versions(self):
        original = "menu_item = self.menu_list.addAction('Open with ' + word)"
        template = 'menu_item = self.menu_list.addAction({text}.format(name=word))'
        for version, config in self.versions.items():
            target = next(item for item in config['files'] if item['path'] == 'widgets/tabs/environments.py')
            rule = next(rule for rule in target['rules'] if rule['id'] == 'env.open_with')
            with self.subTest(version=version):
                self.assertEqual(rule['original'], original)
                self.assertEqual(rule['template'], template)
                self.assertEqual(rule['count'], 1)
            for lang, messages in self.locales.items():
                labels = []
                class Menu:
                    def addAction(self, text):
                        labels.append(text)
                code = template.format(text=json.dumps(messages['env.open_with'], ensure_ascii=False))
                for word in ('Python', 'IPython', 'Jupyter Notebook'):
                    with self.subTest(version=version, language=lang, word=word):
                        exec(code, {}, {'self': type('Widget', (), {'menu_list': Menu()})(), 'word': word})
                        self.assertEqual(labels[-1], messages['env.open_with'].format(name=word))

    def test_toolbox_keeps_dynamic_prefix_and_valid_fstring(self):
        for version, config in self.versions.items():
            target = next(item for item in config['files'] if item['path']=='widgets/main_window/__init__.py')
            rule = next(rule for rule in target['rules'] if rule['id']=='status.verifying_toolbox')
            for lang, messages in self.locales.items():
                expr = rule['template'].format(text=json.dumps(messages[rule['id']], ensure_ascii=False))
                with self.subTest(version=version, language=lang):
                    self.assertIn('toolbox_install_worker.prefix', expr)
                    ast.parse(expr, mode='eval')


if __name__ == '__main__':
    unittest.main()
