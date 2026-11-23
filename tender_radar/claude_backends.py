"""Two ways to reach Claude, with the same `parse()` call.

- ApiBackend: the Messages API, billed per token. Needs ANTHROPIC_API_KEY.
- CliBackend: the Claude Code CLI (`claude -p`), logged in with your Claude subscription. No API key.

`parse()` returns a validated pydantic object, or None when Claude declines or the call fails,
so one failed batch cannot stop a run.
"""

import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# On a policy decline, the API reruns the request on a suitable model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
CLI_TIMEOUT_SECONDS = 600
CLI_CANDIDATES = ("~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude")


class ApiBackend:
    def __init__(self, model: str):
        import anthropic  # imported here so the tool runs without the package in CLI mode

        self.client = anthropic.Anthropic()
        self.model = model

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

    def parse(self, system: str, text: str, schema, effort: str, max_tokens: int, documents=()):
        import anthropic

        content = [_document_block(name, data) for name, data in documents] + [{"type": "text", "text": text}]
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                output_config={"effort": effort},
                system=system,
                messages=[{"role": "user", "content": content if documents else text}],
                output_format=schema,
            )
        except anthropic.APIStatusError as error:
            print(f"  ! Claude API error {error.status_code}: {error.message}", flush=True)
            return None
        except anthropic.APIConnectionError as error:
            print(f"  ! Claude API not reachable: {error}", flush=True)
            return None
        if response.stop_reason in ("refusal", "max_tokens"):
            print(f"  ! Claude stopped: {response.stop_reason}", flush=True)
            return None
        return response.parsed_output


class CliBackend:
    """Runs `claude -p` with no MCP servers and no project settings: a plain structured answer.

    Documents are written to a private temporary folder, and Claude may use its Read tool on that folder
    only. Read sees the pages of a PDF, so scanned documents and newspaper adverts work too.
    """

    def __init__(self, path: str, model: str = ""):
        self.path = path
        self.model = model or "Claude Code default"
        self._model_flag = ["--model", model] if model else []

    @staticmethod
    def find(configured: str = "") -> str:
        """The claude executable. launchd services get a short PATH, so the usual install places are tried too."""
        for candidate in (configured, shutil.which("claude"), *CLI_CANDIDATES):
            if candidate and os.access(Path(candidate).expanduser(), os.X_OK):
                return str(Path(candidate).expanduser())
        return ""

    def parse(self, system: str, text: str, schema, effort: str, max_tokens: int, documents=()):
        # A neutral folder as the working directory, so the CLI does not read this project's CLAUDE.md.
        with tempfile.TemporaryDirectory(prefix="tender-radar-") as folder:
            paths = _write_documents(Path(folder), documents)
            tools = ["--tools", "Read", "--allowedTools", f"Read({folder}/**)"] if paths else ["--tools", ""]
            listing = "".join(f"Document file: {path}\n" for path in paths)
            prompt = (f"{listing}Read every document file with the Read tool first.\n\n" if paths else "") + text
            command = [
                self.path, "-p", "--output-format", "json", "--no-session-persistence", *tools,
                "--strict-mcp-config", "--setting-sources", "", "--effort", effort,
                "--system-prompt", system, "--json-schema", json.dumps(schema.model_json_schema()), *self._model_flag,
            ]
            reply = self._run(command, prompt, folder)
        if reply is None:
            return None
        if reply.get("is_error") or reply.get("subtype") != "success":
            print(f"  ! Claude CLI error: {str(reply.get('result'))[:300]}", flush=True)
            return None
        try:
            return schema.model_validate_json(_strip_fence(reply.get("result") or ""))
        except ValueError as error:
            print(f"  ! Claude CLI answer did not match the schema: {error}", flush=True)
            return None

    def _run(self, command: list[str], prompt: str, folder: str):
        try:
            done = subprocess.run(
                command, input=prompt, capture_output=True, text=True, timeout=CLI_TIMEOUT_SECONDS, cwd=folder,
            )
            return json.loads(done.stdout)
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
            print(f"  ! Claude CLI failed: {error}", flush=True)
            return None


def _document_block(name: str, data: bytes) -> dict:
    if name.lower().endswith((".jpg", ".jpeg", ".png")):
        media_type = "image/png" if name.lower().endswith(".png") else "image/jpeg"
        return {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                            "data": base64.standard_b64encode(data).decode("ascii")}}
    if name.lower().endswith(".pdf"):
        encoded = base64.standard_b64encode(data).decode("ascii")
        source = {"type": "base64", "media_type": "application/pdf", "data": encoded}
    else:
        source = {"type": "text", "media_type": "text/plain", "data": data.decode("utf-8", errors="replace")}
    return {"type": "document", "source": source, "title": name}


def _write_documents(folder: Path, documents) -> list[str]:
    """Each document as a file in `folder`. Only the base name is kept, so a name cannot point elsewhere."""
    paths = []
    for index, (name, data) in enumerate(documents):
        path = folder / f"{index}-{Path(name).name or 'document'}"
        path.write_bytes(data)
        paths.append(str(path))
    return paths


def _strip_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    return text
