import datetime as dt
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('signing', Path(__file__).with_name('install-signing.py'))
signing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signing)


class ProfileValidation(unittest.TestCase):
    def setUp(self):
        self.profile = {
            'ExpirationDate': dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30),
            'UUID': '12345678-1234-1234-1234-123456789012',
            'TeamIdentifier': ['ABCDEFGHIJ'],
            'Entitlements': {'application-identifier': 'ABCDEFGHIJ.app.dishplay.capture', 'get-task-allow': False, 'beta-reports-active': True},
        }

    def validate(self, profile):
        return signing.validate_profile(profile, 'ABCDEFGHIJ', 'app.dishplay.capture')

    def test_accepts_exact_app_store_profile(self):
        self.assertEqual(self.validate(self.profile), self.profile['UUID'])

    def test_rejects_other_team_or_app(self):
        for key, value in [('TeamIdentifier', ['OTHERTEAM1']), ('Entitlements', {**self.profile['Entitlements'], 'application-identifier': 'ABCDEFGHIJ.another.app'})]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate({**self.profile, key: value})

    def test_rejects_development_adhoc_enterprise_and_missing_beta(self):
        changes = [{'ProvisionedDevices': ['device']}, {'ProvisionsAllDevices': True},
                   {'Entitlements': {**self.profile['Entitlements'], 'get-task-allow': True}},
                   {'Entitlements': {**self.profile['Entitlements'], 'beta-reports-active': False}}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate({**self.profile, **change})

    def test_rejects_expiring_profile_and_path_like_uuid(self):
        for change in [{'ExpirationDate': dt.datetime.now(dt.timezone.utc)}, {'UUID': '../../someone-elses-profile'}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate({**self.profile, **change})


if __name__ == '__main__':
    unittest.main()
