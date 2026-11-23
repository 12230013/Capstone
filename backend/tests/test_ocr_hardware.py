import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from app.ocr.hardware import select_hardware

class HardwareTests(unittest.TestCase):
    def paddle(self,compiled=False,count=0):
        return SimpleNamespace(is_compiled_with_cuda=lambda:compiled,device=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda:count)))

    def test_apple_silicon_uses_metal_and_cpu_layout(self):
        probe=Mock()
        result=select_hardware(system='Darwin',machine='arm64',paddle_module=probe,nvidia_probe=probe,cpu_threads=10)
        self.assertEqual((result.backend,result.device,result.recognition_device),('mlx-vlm-server','cpu','metal'))
        self.assertEqual(result.cpu_threads,10)
        probe.assert_not_called()

    def test_windows_with_cuda_runtime_uses_nvidia_gpu(self):
        result=select_hardware(system='Windows',machine='AMD64',paddle_module=self.paddle(True,1),nvidia_probe=lambda:True)
        self.assertEqual((result.backend,result.device),('native','gpu:0'))

    def test_windows_cpu_build_with_nvidia_does_not_silently_use_cpu(self):
        with self.assertRaisesRegex(RuntimeError,'paddlepaddle-gpu'):
            select_hardware(system='Windows',machine='AMD64',paddle_module=self.paddle(),nvidia_probe=lambda:True)

    def test_no_compatible_gpu_reports_cpu(self):
        result=select_hardware(system='Windows',machine='AMD64',paddle_module=self.paddle(),nvidia_probe=lambda:False)
        self.assertEqual(result.recognition_device,'cpu')

    def test_explicit_cpu_and_invalid_thread_count(self):
        result=select_hardware(backend='native',device='cpu',system='Windows',machine='AMD64')
        self.assertEqual(result.device,'cpu')
        with self.assertRaises(ValueError):select_hardware(cpu_threads=-1)

    def test_linux_cuda_and_cuda_driver_failure(self):
        result=select_hardware(system='Linux',machine='x86_64',paddle_module=self.paddle(True,2),nvidia_probe=lambda:True)
        self.assertEqual(result.device,'gpu:0')
        module=self.paddle(True,1);module.device.cuda.device_count=Mock(side_effect=RuntimeError('driver'))
        with self.assertRaisesRegex(RuntimeError,'driver'):
            select_hardware(system='Windows',machine='AMD64',paddle_module=module)
