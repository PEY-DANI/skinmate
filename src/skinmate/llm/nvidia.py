"""NVIDIA NIM API 기반 LLMProvider 구현.

OpenAI 호환 API 클라이언트를 사용하여 integrate.api.nvidia.com 을 호출한다.
"""

from __future__ import annotations

import json

from skinmate.errors import LLMError

DEFAULT_MODEL = "openai/gpt-oss-120b"


class NvidiaProvider:
    """NVIDIA NIM API (OpenAI 호환) 기반 LLMProvider.

    `LLMProvider` Protocol을 구조적으로 만족한다.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = "https://integrate.api.nvidia.com/v1"

    def complete(self, system: str, prompt: str) -> str:
        """자유 텍스트 응답 생성. 자연스러움을 위해 temperature=0.7 적용."""
        return self._generate(system, prompt, temperature=0.7)

    def complete_json(
        self, system: str, prompt: str, schema: dict[str, object]
    ) -> dict[str, object]:
        """JSON 구조화 출력. 구조 정확성을 위해 temperature=0.2 적용 및 강건한 파싱."""
        full_prompt = f"{prompt}\n\n[출력 JSON 스키마]\n{json.dumps(schema, ensure_ascii=False)}"
        text = self._generate(system, full_prompt, temperature=0.2)

        # JSON 클렌징 (마크다운 백틱 및 양끝 공백 제거)
        cleaned_text = text.strip()
        if cleaned_text.startswith("```"):
            lines = cleaned_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned_text = "\n".join(lines).strip()

        try:
            # 첫 번째 유효한 JSON 객체 시작 위치 '{' 검색하여 파싱 강건화
            start = cleaned_text.index("{")
            cleaned_text = cleaned_text[start:]
            obj, _ = json.JSONDecoder().raw_decode(cleaned_text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise LLMError(f"NVIDIA JSON 파싱 실패: {exc}. 원본: {text!r}") from exc

        if not isinstance(obj, dict):
            raise LLMError("NVIDIA JSON 최상위가 object가 아님")
        return obj

    def _generate(self, system: str, prompt: str, temperature: float) -> str:
        """NVIDIA NIM API chat completion을 호출하며, 발생한 에러를 LLMError로 래핑."""
        from openai import OpenAI

        if not self._api_key:
            raise LLMError("NVIDIA API Key (OPENAI_API_KEY)가 설정되어 있지 않습니다.")

        client = OpenAI(base_url=self._base_url, api_key=self._api_key)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

        try:
            completion = client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=temperature,
                max_tokens=4096,
                stream=False,
            )
            content = completion.choices[0].message.content
            if not content:
                raise LLMError("NVIDIA 빈 응답")
            return str(content)
        except Exception as exc:
            raise LLMError(f"NVIDIA NIM API 호출 실패: {exc}") from exc
