import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


SERVICE_PATH = Path(__file__).resolve().parents[1] / "services" / "account_push_service.py"


class AccountPushServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = types.ModuleType("curl_cffi.requests")
        curl_cffi = types.ModuleType("curl_cffi")
        curl_cffi.requests = cls.requests
        with patch.dict(sys.modules, {"curl_cffi": curl_cffi}):
            spec = importlib.util.spec_from_file_location("account_push_service_under_test", SERVICE_PATH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        cls.service_class = module.AccountPushService

    def setUp(self):
        self.service = self.service_class()
        self.service.configure({"enabled": True, "api_url": "https://remote.example/", "api_key": "secret"})
        self.account = {"access_token": "token", "email": "test@example.com"}

    def test_confirmed_import(self):
        self.requests.post = Mock(return_value=Mock(status_code=200, json=Mock(return_value={"added": 1, "skipped": 0, "errors": []})))
        result = self.service.push_account(self.account, record_status=False)
        self.assertTrue(result["ok"])
        url = self.requests.post.call_args.args[0]
        payload = self.requests.post.call_args.kwargs["json"]
        self.assertEqual(url, "https://remote.example/api/accounts")
        self.assertEqual(payload["accounts"][0]["access_token"], "token")
        self.assertEqual(payload["refresh"], False)
        self.assertEqual(payload["return_items"], False)

    def test_http_failure(self):
        self.requests.post = Mock(return_value=Mock(status_code=401, text="unauthorized"))
        result = self.service.push_account(self.account, record_status=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 401)

    def test_http_success_without_confirmed_import(self):
        self.requests.post = Mock(return_value=Mock(status_code=200, json=Mock(return_value={"added": 0, "skipped": 0, "errors": []})))
        result = self.service.push_account(self.account, record_status=False)
        self.assertFalse(result["ok"])
        self.assertIn("did not confirm", result["error"])

    def test_http_success_with_business_errors(self):
        self.requests.post = Mock(return_value=Mock(status_code=200, json=Mock(return_value={"added": 1, "errors": ["invalid token"]})))
        result = self.service.push_account(self.account, record_status=False)
        self.assertFalse(result["ok"])
        self.assertIn("invalid token", result["error"])


if __name__ == "__main__":
    unittest.main()
