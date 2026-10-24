"""Configuration regressions; no GPU, Docker daemon, model download, or secrets."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        shutil.copy2(ROOT / "compose-model", self.work / "compose-model")
        shutil.copytree(ROOT / "model-presets", self.work / "model-presets")
        (self.work / ".env").write_text("INFERENCE_BACKEND=vllm-bolt\n")
        docker = self.work / "docker"
        docker.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        docker.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.work}:{os.environ['PATH']}")

    def invoke(self, name):
        return subprocess.run(
            ["./compose-model", f"model-presets/{name}.env", "-p", "telegram-bot", "config"],
            cwd=self.work, env=self.env, capture_output=True, text=True,
        )

    def test_bolt_selects_override_and_forwards_arguments(self):
        result = self.invoke("nemotron-3.5-bolt")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "compose", "--env-file", ".env", "--env-file",
            "model-presets/nemotron-3.5-bolt.env", "-f", "docker-compose.yml",
            "-f", "docker-compose.bolt.yml", "-p", "telegram-bot", "config",
        ])

    def test_existing_presets_ignore_backend_in_root_env(self):
        for preset in (ROOT / "model-presets").glob("*.env"):
            if preset.stem == "nemotron-3.5-bolt":
                continue
            with self.subTest(preset=preset.name):
                result = self.invoke(preset.stem)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("docker-compose.yml", result.stdout)
                self.assertNotIn("docker-compose.bolt.yml", result.stdout)

    def test_invalid_backend_is_rejected_without_executing_preset(self):
        (self.work / "model-presets" / "invalid.env").write_text(
            'INFERENCE_BACKEND=$(touch executed)\n'
        )
        result = self.invoke("invalid")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsupported INFERENCE_BACKEND", result.stderr)
        self.assertFalse((self.work / "executed").exists())

    def test_missing_env_is_actionable(self):
        (self.work / ".env").unlink()
        result = self.invoke("nemotron-3.5-bolt")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Missing .env", result.stderr)


class ComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("docker"):
            raise unittest.SkipTest("Docker Compose CLI is not installed")
        check = subprocess.run(["docker", "compose", "version"], capture_output=True)
        if check.returncode:
            raise unittest.SkipTest("Docker Compose CLI is not available")

    def config(self, preset, bolt=False):
        command = ["docker", "compose", "--env-file", ".env.example",
                   "--env-file", f"model-presets/{preset}.env",
                   "-p", "telegram-bot", "-f", "docker-compose.yml"]
        if bolt:
            command += ["-f", "docker-compose.bolt.yml"]
        command += ["--profile", "web", "config", "--format", "json"]
        # Simulate stale NIM settings in a deployment's shell. Bolt must not
        # forward these, even if they remain in .env or the parent environment.
        env = dict(os.environ, NIM_MODEL_PROFILE="stale-profile",
                   NIM_PASSTHROUGH_ARGS="stale-parser", NGC_API_KEY="test-only")
        result = subprocess.run(command, cwd=ROOT, env=env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_bolt_replaces_runtime_but_preserves_clients_and_data(self):
        config = self.config("nemotron-3.5-bolt", bolt=True)
        services = config["services"]
        nim = services["nim"]
        self.assertEqual(set(nim["environment"]),
                         {"HF_TOKEN", "HF_HOME", "VLLM_USE_V2_MODEL_RUNNER"})
        self.assertEqual(nim["volumes"][0]["source"], "bolt-cache")
        self.assertEqual(len(nim["volumes"]), 1)
        self.assertEqual(nim["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(len(nim["ports"]), 1)
        self.assertEqual(nim["restart"], "always")
        self.assertIn("/health", nim["healthcheck"]["test"][-1])
        self.assertTrue(nim["build"]["context"].endswith("inference/bolt"))
        revision = nim["build"]["args"]["MODEL_REVISION"]
        args = nim["command"]
        self.assertEqual(args[args.index("--revision") + 1], revision)
        self.assertEqual(args[args.index("--code-revision") + 1], revision)
        model = "nvidia/NVIDIA-Nemotron-3.5-Bolt-74B-A9B-24GB"
        self.assertEqual(args[0], model)
        self.assertEqual(services["bot"]["environment"]["MODEL_NAME"], model)
        self.assertEqual(services["bot"]["environment"]["MAX_TOKENS"], "16384")
        self.assertEqual(services["bot"]["volumes"][0]["source"], "bot-data")
        self.assertEqual(services["open-webui"]["volumes"][0]["source"], "openwebui-data")
        for name in ["bot", "open-webui"]:
            self.assertEqual(services[name]["depends_on"]["nim"]["condition"],
                             "service_healthy")

    def test_existing_nim_presets_do_not_gain_bolt_runtime(self):
        for preset in (ROOT / "model-presets").glob("*.env"):
            if preset.stem == "nemotron-3.5-bolt":
                continue
            with self.subTest(preset=preset.name):
                nim = self.config(preset.stem)["services"]["nim"]
                self.assertNotIn("build", nim)
                self.assertIsNone(nim.get("command"))
                self.assertTrue(nim["image"].startswith("nvcr.io/nim/"))
                self.assertEqual(nim["volumes"][0]["source"], "nim-cache")
                self.assertIn("NIM_MAX_MODEL_LEN", nim["environment"])
                self.assertIn("/v1/health/ready", nim["healthcheck"]["test"][-1])


if __name__ == "__main__":
    unittest.main()
