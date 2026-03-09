"""
엔진1: SequenceAnomalyEngine — BERT4ETH 참조 계정 행동 순차 분석
[PLACEHOLDER] 실제 BERT 추론 대신 규칙 기반 이동평균 시뮬레이션

논문 참조: "Inspired by BERT4ETH [Hu et al., WWW'23]"
실제 연동 지점: analyze() 내부를 ONNX Runtime / TorchServe 호출로 교체

BERT4ETH 원본 구조 (참조용):
  1. gen_seq.py       → 계정별 트랜잭션 시퀀스 생성
  2. gen_pretrain.py  → MLM 마스킹 데이터 생성
  3. run_pretrain.py  → Transformer 사전학습
  4. output_embed.py  → 계정 임베딩 벡터 출력
  5. run_phishing_detection.py → 다운스트림 분류
"""

import time
from typing import Dict, Any, List, Optional
from .base import EngineBase, EngineResult, ThreatLevel


class SequenceAnomalyEngine(EngineBase):
    """
    BERT4ETH 스타일 계정 행동 순차 분석 엔진.

    [PLACEHOLDER 구현]
    - 실제: BERT 임베딩 → anomaly score
    - 현재: 최근 거래 이동평균 기반 이상치 탐지

    교체 방법:
    ```python
    # analyze() 내부를 아래로 교체:
    embedding = self.onnx_session.run(None, {"input": seq_tensor})
    score = self.classifier.predict(embedding)[0]
    ```
    """

    # 기본 설정
    DEFAULT_CONFIG = {
        "window_size": 10,          # 이동평균 윈도우 크기
        "spike_threshold": 3.0,     # 이동평균 대비 배수 (HIGH 판정)
        "moderate_threshold": 2.0,  # 이동평균 대비 배수 (MEDIUM 판정)
        "min_history": 3,           # 최소 이력 수 (이 미만이면 판정 보류)
        "max_history": 50,          # 계정당 최대 이력 보관 수
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        merged = {**self.DEFAULT_CONFIG, **(config or {})}
        super().__init__("SequenceAnomalyEngine", merged)
        self.is_placeholder = True  # ← 명시적 placeholder 표기
        self._account_history: Dict[str, List[float]] = {}

    def analyze(self, tx_data: Dict[str, Any]) -> EngineResult:
        start = time.time()

        address = tx_data.get("from", "0x0")
        amount = float(tx_data.get("amount", 0))
        tx_type = tx_data.get("type", "unknown")

        # ── 이력 갱신 ──
        history = self._account_history.setdefault(address, [])
        history.append(amount)
        max_hist = self.config["max_history"]
        if len(history) > max_hist:
            self._account_history[address] = history[-max_hist:]
            history = self._account_history[address]

        # ── PLACEHOLDER 분석 로직 ──
        threat = ThreatLevel.NONE
        confidence = 0.05
        method = "placeholder_moving_avg"

        window = self.config["window_size"]
        min_hist = self.config["min_history"]

        if len(history) >= min_hist:
            # 최근 윈도우 이동평균
            recent = history[-window:] if len(history) >= window else history
            avg = sum(recent) / len(recent)
            std = (sum((x - avg) ** 2 for x in recent) / len(recent)) ** 0.5

            if avg > 0:
                ratio = amount / avg
            else:
                ratio = 0.0

            # Z-score 기반 이상치 판정
            z_score = (amount - avg) / std if std > 0 else 0.0

            if ratio >= self.config["spike_threshold"] or z_score > 3.0:
                threat = ThreatLevel.HIGH
                confidence = min(0.85, 0.5 + ratio * 0.1)
            elif ratio >= self.config["moderate_threshold"] or z_score > 2.0:
                threat = ThreatLevel.MEDIUM
                confidence = min(0.65, 0.3 + ratio * 0.1)
            elif ratio >= 1.5:
                threat = ThreatLevel.LOW
                confidence = 0.25
        else:
            method = "insufficient_history"

        # ── 특수 케이스: 대규모 첫 TX ──
        if len(history) <= 2 and amount > 1_000_000:
            threat = ThreatLevel.MEDIUM
            confidence = max(confidence, 0.4)
            method = "large_initial_tx"

        latency = (time.time() - start) * 1000
        self.record_call(latency)

        return EngineResult(
            engine_name=self.name,
            threat_level=threat,
            confidence=confidence,
            details={
                "method": method,
                "history_len": len(history),
                "address": address[:10] + "...",
                # ↓ 실제 연동 시 추가될 필드
                # "bert_embedding": [...],
                # "anomaly_score": 0.87,
                # "sequence_length": 100,
            },
            latency_ms=latency,
        )

    def reset_history(self, address: Optional[str] = None):
        """계정 이력 초기화"""
        if address:
            self._account_history.pop(address, None)
        else:
            self._account_history.clear()

    def get_engine_info(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "reference": "BERT4ETH [Hu et al., WWW'23]",
            "status": "placeholder",
            "description": (
                "Moving-average heuristic simulating BERT4ETH's sequential "
                "account behavior analysis. Replace analyze() body with "
                "ONNX Runtime inference for production."
            ),
            "real_integration_point": (
                "Replace analyze() body with:\n"
                "  embedding = onnx_session.run(None, {'input': seq_tensor})\n"
                "  score = classifier.predict(embedding)"
            ),
        }
