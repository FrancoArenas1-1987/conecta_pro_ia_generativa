from __future__ import annotations

import json
import subprocess

from ..exceptions import GenerationError


class OllamaProvider:
    def __init__(self, model: str, executable: str = "ollama") -> None:
        self.model = model
        self.executable = executable

    def _run(self, prompt: str) -> str:
        cmd = [self.executable, "run", self.model]
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GenerationError(f"Ollama executable not found: {self.executable}") from exc

        if proc.returncode != 0:
            raise GenerationError(f"Ollama error: {proc.stderr.strip() or proc.stdout.strip()}")
        output = proc.stdout.strip()
        if not output:
            raise GenerationError("Ollama returned empty output")
        return output

    @staticmethod
    def _extract_json(raw: str) -> dict:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end < 0 or end <= start:
            raise GenerationError("Model output is not valid JSON")
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise GenerationError(f"Failed to parse model JSON: {exc}") from exc

    def generate_json(self, prompt: str) -> dict:
        return self._extract_json(self._run(prompt))
