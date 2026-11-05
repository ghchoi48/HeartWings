import ssl
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from maeumnarae.services import weather, tls


class WeatherConnectionTests(unittest.TestCase):
    def test_windows_loads_system_and_bundled_roots_with_verification(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.verify_flags |= ssl.VERIFY_X509_STRICT
        original_flags = context.verify_flags
        with patch.object(tls.sys, 'platform', 'win32'), \
                patch.object(tls.ssl, 'create_default_context', return_value=context) as create:
            result = weather._ssl_context()
        create.assert_called_once_with()
        self.assertGreater(len(result.get_ca_certs()), 0)
        self.assertEqual(result.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(result.check_hostname)
        self.assertEqual(result.verify_flags, original_flags & ~ssl.VERIFY_X509_STRICT)

    def test_macos_keeps_existing_certificate_policy(self):
        with patch.object(tls.sys, 'platform', 'darwin'), \
                patch.object(tls.ssl, 'create_default_context') as create:
            self.assertIs(weather._ssl_context(), create.return_value)
        create.assert_called_once_with(cafile=tls.certifi.where())

    def test_request_uses_context_and_reads_json(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"results": []}'
        with patch.object(weather, '_ssl_context') as context, \
                patch.object(weather, 'urlopen', return_value=response) as open_url:
            self.assertEqual(weather.request('https://example.com', {'name': 'Seoul'}), {'results': []})
        open_url.assert_called_once_with('https://example.com?name=Seoul', timeout=12,
                                         context=context.return_value)

    def test_certificate_failure_is_not_retried_without_verification(self):
        error = URLError(ssl.SSLCertVerificationError('untrusted certificate'))
        with patch.object(weather, '_ssl_context'), \
                patch.object(weather, 'urlopen', side_effect=error) as open_url:
            with self.assertRaises(weather.WeatherError):
                weather.request('https://example.com', {})
        self.assertEqual(open_url.call_count, 1)


if __name__ == '__main__':
    unittest.main()
