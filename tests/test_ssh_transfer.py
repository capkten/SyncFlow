import unittest
from unittest.mock import MagicMock, patch

from backend.core.transfer import SSHTransfer


class TestSSHTransfer(unittest.TestCase):
    @patch('backend.core.transfer.SSHClient')
    def test_reject_policy(self, mock_client):
        client = MagicMock()
        client.open_sftp.return_value = MagicMock()
        mock_client.return_value = client

        transfer = SSHTransfer(
            host='127.0.0.1',
            port=22,
            username='user',
            password='pass',
            host_key_policy='reject',
            known_hosts_path=None
        )
        transfer.connect()

        args, _ = client.set_missing_host_key_policy.call_args
        self.assertEqual(args[0].__class__.__name__, 'RejectPolicy')

    @patch('backend.core.transfer.SSHClient')
    def test_auto_policy_saves_host_key(self, mock_client):
        client = MagicMock()
        client.open_sftp.return_value = MagicMock()
        mock_client.return_value = client

        transfer = SSHTransfer(
            host='127.0.0.1',
            port=22,
            username='user',
            password='pass',
            host_key_policy='auto',
            known_hosts_path='./tests/data/known_hosts'
        )
        transfer.connect()

        client.save_host_keys.assert_called()


if __name__ == '__main__':
    unittest.main()
