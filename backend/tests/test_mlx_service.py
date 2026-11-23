import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from app.ocr import mlx_service

class MLXServiceTests(unittest.TestCase):
    def test_existing_healthy_service_is_reused(self):
        with tempfile.TemporaryDirectory() as d, patch.object(mlx_service,'SERVICE_DIRECTORY',Path(d)), patch.object(mlx_service,'_health',return_value={'status':'healthy','loaded_model':'vl'}), patch.object(mlx_service.subprocess,'Popen') as spawn:
            self.assertEqual(mlx_service.ensure_mlx_service('http://127.0.0.1:8111/')['status'],'healthy')
            spawn.assert_not_called()

    def test_local_service_starts_with_single_sequence_and_loopback_binding(self):
        process=Mock(pid=123);process.poll.return_value=None
        with tempfile.TemporaryDirectory() as d, patch.object(mlx_service,'SERVICE_DIRECTORY',Path(d)), patch.object(mlx_service,'_health',side_effect=[None,{'status':'healthy','loaded_model':None}]), patch.object(mlx_service.socket,'socket') as sock, patch.object(mlx_service.subprocess,'Popen',return_value=process) as spawn, patch.object(Path,'is_file',return_value=True):
            sock.return_value.__enter__.return_value.connect_ex.return_value=1
            mlx_service.ensure_mlx_service('http://127.0.0.1:8111/')
            command=spawn.call_args.args[0]
            self.assertIn('mlx_vlm.server',command)
            self.assertIn('127.0.0.1',command)
            self.assertEqual(command[command.index('--max-num-seqs')+1],'1')

    def test_foreign_port_and_remote_urls_fail_without_spawning(self):
        with self.assertRaisesRegex(RuntimeError,'loopback'):
            mlx_service.ensure_mlx_service('http://example.com:8111/')
        with tempfile.TemporaryDirectory() as d, patch.object(mlx_service,'SERVICE_DIRECTORY',Path(d)), patch.object(mlx_service,'_health',return_value=None), patch.object(mlx_service.socket,'socket') as sock, patch.object(mlx_service.subprocess,'Popen') as spawn:
            sock.return_value.__enter__.return_value.connect_ex.return_value=0
            with self.assertRaisesRegex(RuntimeError,'occupied'):
                mlx_service.ensure_mlx_service('http://127.0.0.1:8111/')
            spawn.assert_not_called()

    def test_stop_refuses_to_signal_an_unrelated_process(self):
        with tempfile.TemporaryDirectory() as d, patch.object(mlx_service,'SERVICE_DIRECTORY',Path(d)), patch.object(mlx_service.subprocess,'run',return_value=Mock(returncode=0,stdout='/bin/zsh')), patch.object(mlx_service.os,'kill') as kill:
            (Path(d)/'mlx-server.pid').write_text('123')
            with self.assertRaisesRegex(RuntimeError,'refusing'):
                mlx_service.stop_mlx_service()
            kill.assert_not_called()
