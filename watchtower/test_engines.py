"""
엔진 단위 테스트 + 통합 테스트
테스트 시나리오 T1~T10 (implementation_plan.md 참조)

실행: python -m pytest watchtower/test_engines.py -v
또는: cd watchtower && python test_engines.py
"""

import sys
import os
import json
import time
import unittest

# 경로 설정
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.engines.base import ThreatLevel, EngineResult, ThreatSignal
from lib.engines.sequence_anomaly import SequenceAnomalyEngine
from lib.engines.flash_loan_rule import FlashLoanRuleEngine
from lib.engines.houston_lite import HoustonLiteInvariantChecker
from lib.engines.aggregator import ThreatAggregator


# ═══════════════════════════════════════════════════════════════════════════
# T1~T6: 엔진 단위 테스트
# ═══════════════════════════════════════════════════════════════════════════

class TestSequenceAnomalyEngine(unittest.TestCase):
    """엔진1: SequenceAnomalyEngine (PLACEHOLDER) 테스트"""

    def setUp(self):
        self.engine = SequenceAnomalyEngine()

    def test_t1_normal_small_transfer(self):
        """T1: 정상 소액 이체 → NONE"""
        # 이력 쌓기
        for _ in range(5):
            self.engine.analyze({"from": "0xUser1", "amount": 500, "type": "transfer"})
        result = self.engine.analyze({"from": "0xUser1", "amount": 500, "type": "transfer"})
        self.assertEqual(result.threat_level, ThreatLevel.NONE)
        self.assertLess(result.confidence, 0.3)

    def test_t5_gradual_increase(self):
        """T5: 점진적 증가 → 이동평균 이탈 탐지"""
        # 정상 이력
        for _ in range(10):
            self.engine.analyze({"from": "0xAttacker", "amount": 1000, "type": "transfer"})
        # 급증
        result = self.engine.analyze({"from": "0xAttacker", "amount": 16000, "type": "transfer"})
        self.assertIn(result.threat_level, [ThreatLevel.HIGH, ThreatLevel.MEDIUM])

    def test_placeholder_flag(self):
        """Placeholder 표기 확인"""
        self.assertTrue(self.engine.is_placeholder)
        info = self.engine.get_engine_info()
        self.assertEqual(info["status"], "placeholder")

    def test_large_initial_tx(self):
        """대규모 첫 TX 탐지"""
        result = self.engine.analyze({"from": "0xNew", "amount": 5_000_000, "type": "mint"})
        self.assertGreaterEqual(result.threat_level, ThreatLevel.MEDIUM)


class TestFlashLoanRuleEngine(unittest.TestCase):
    """엔진2: FlashLoanRuleEngine (LITE) 테스트"""

    def setUp(self):
        self.engine = FlashLoanRuleEngine()

    def test_t1_normal_transfer(self):
        """T1: 정상 소액 이체 → NONE"""
        result = self.engine.analyze({
            "from": "0xUser1", "amount": 500, "type": "transfer",
            "call_sequence": ["transfer"],
        })
        self.assertEqual(result.threat_level, ThreatLevel.NONE)

    def test_t3_infinite_mint(self):
        """T3: 단발성 대량 민트 → HIGH/CRITICAL"""
        result = self.engine.analyze({
            "from": "0xAttacker", "amount": 5_000_000, "type": "mint",
            "call_sequence": ["mint", "mint", "transfer"],
        })
        self.assertIn(result.threat_level, [ThreatLevel.HIGH, ThreatLevel.CRITICAL])

    def test_t4_flash_loan_attack(self):
        """T4: Flash Loan 공격 시퀀스 → CRITICAL"""
        result = self.engine.analyze({
            "from": "0xAttacker", "amount": 10_000_000, "type": "flash_loan",
            "call_sequence": ["flashLoan", "swap", "manipulate", "repay"],
        })
        self.assertEqual(result.threat_level, ThreatLevel.CRITICAL)
        self.assertGreater(result.confidence, 0.7)
        self.assertEqual(result.details["matched_pattern"], "flash_loan_standard")

    def test_reentrancy_pattern(self):
        """Reentrancy 공격 패턴 탐지"""
        result = self.engine.analyze({
            "from": "0xAttacker", "amount": 100_000, "type": "exploit",
            "call_sequence": ["withdraw", "fallback", "withdraw"],
        })
        self.assertEqual(result.threat_level, ThreatLevel.CRITICAL)

    def test_amount_anomaly(self):
        """금액 이상 탐지 (시퀀스 없이)"""
        result = self.engine.analyze({
            "from": "0xAttacker", "amount": 1_000_000, "type": "mint",
            "call_sequence": [],
        })
        self.assertGreaterEqual(result.threat_level, ThreatLevel.HIGH)

    def test_not_placeholder(self):
        """Lite 구현 표기 확인"""
        self.assertFalse(self.engine.is_placeholder)
        info = self.engine.get_engine_info()
        self.assertEqual(info["status"], "lite")


class TestHoustonLiteInvariantChecker(unittest.TestCase):
    """엔진3: HoustonLiteInvariantChecker (LITE) 테스트"""

    def setUp(self):
        self.engine = HoustonLiteInvariantChecker()

    def test_t1_normal_no_violation(self):
        """T1: 정상 상태 → 위반 없음"""
        result = self.engine.analyze({
            "from": "0xUser1", "amount": 500, "type": "transfer",
            "state_before": {
                "total_supply": 1_000_000, "initial_supply": 1_000_000,
                "reserve": 500_000, "price": 1.0, "mint_limit": 500_000,
            },
            "state_after": {
                "total_supply": 1_000_000, "reserve": 500_000, "price": 1.0,
                "period_mint_amount": 0,
            },
        })
        self.assertEqual(result.threat_level, ThreatLevel.NONE)
        self.assertEqual(len(result.details["violations"]), 0)

    def test_t6_supply_cap_violation(self):
        """T6: totalSupply > initial * 2 → CRITICAL 위반"""
        result = self.engine.analyze({
            "from": "0xAttacker", "amount": 3_000_000, "type": "mint",
            "state_before": {
                "total_supply": 1_000_000, "initial_supply": 1_000_000,
                "reserve": 500_000, "price": 1.0, "mint_limit": 500_000,
            },
            "state_after": {
                "total_supply": 4_000_000,  # > 2M (initial * 2)
                "reserve": 500_000, "price": 1.0,
                "period_mint_amount": 3_000_000,
            },
        })
        self.assertEqual(result.threat_level, ThreatLevel.CRITICAL)
        self.assertIn("total_supply_cap", result.details["violations"])

    def test_reserve_ratio_violation(self):
        """Reserve ratio < 10% → HIGH 위반"""
        result = self.engine.analyze({
            "from": "0xAttacker", "amount": 400_000, "type": "drain",
            "state_before": {
                "total_supply": 1_000_000, "initial_supply": 1_000_000,
                "reserve": 500_000, "price": 1.0, "mint_limit": 500_000,
            },
            "state_after": {
                "total_supply": 1_000_000,
                "reserve": 50_000,  # 5% < 10%
                "price": 1.0, "period_mint_amount": 0,
            },
        })
        self.assertIn("reserve_ratio", result.details["violations"])

    def test_price_stability_violation(self):
        """Price deviation > 20% → MEDIUM 위반"""
        result = self.engine.analyze({
            "from": "0xAttacker", "amount": 100_000, "type": "swap",
            "state_before": {
                "total_supply": 1_000_000, "initial_supply": 1_000_000,
                "reserve": 500_000, "price": 1.0, "mint_limit": 500_000,
            },
            "state_after": {
                "total_supply": 1_000_000, "reserve": 500_000,
                "price": 0.5,  # 50% drop > 20%
                "period_mint_amount": 0,
            },
        })
        self.assertIn("price_stability", result.details["violations"])

    def test_list_invariants(self):
        """Invariant 목록 조회"""
        invariants = self.engine.list_invariants()
        self.assertGreaterEqual(len(invariants), 5)
        names = [inv["name"] for inv in invariants]
        self.assertIn("total_supply_cap", names)
        self.assertIn("reserve_ratio", names)


# ═══════════════════════════════════════════════════════════════════════════
# ThreatAggregator 테스트
# ═══════════════════════════════════════════════════════════════════════════

class TestThreatAggregator(unittest.TestCase):
    """ThreatAggregator 테스트"""

    def setUp(self):
        self.aggregator = ThreatAggregator()

    def test_all_none(self):
        """3개 엔진 모두 NONE → action=none"""
        results = [
            EngineResult("E1", ThreatLevel.NONE, 0.05, {}, 1.0),
            EngineResult("E2", ThreatLevel.NONE, 0.05, {}, 1.0),
            EngineResult("E3", ThreatLevel.NONE, 0.05, {}, 1.0),
        ]
        signal = self.aggregator.aggregate(results)
        self.assertEqual(signal.recommended_action, "none")
        self.assertLess(signal.final_score, 0.2)

    def test_critical_override(self):
        """하나라도 CRITICAL + high confidence → pause"""
        results = [
            EngineResult("SequenceAnomalyEngine", ThreatLevel.NONE, 0.1, {}, 1.0),
            EngineResult("FlashLoanRuleEngine", ThreatLevel.CRITICAL, 0.92, {}, 1.0),
            EngineResult("HoustonLiteInvariantChecker", ThreatLevel.NONE, 0.1, {}, 1.0),
        ]
        signal = self.aggregator.aggregate(results)
        self.assertGreaterEqual(signal.final_score, 0.65)
        self.assertIn(signal.recommended_action, ["pause_macro", "pause_all"])

    def test_mixed_signals(self):
        """혼합 시그널 → 가중 앙상블"""
        results = [
            EngineResult("SequenceAnomalyEngine", ThreatLevel.MEDIUM, 0.5, {}, 1.0),
            EngineResult("FlashLoanRuleEngine", ThreatLevel.HIGH, 0.7, {}, 1.0),
            EngineResult("HoustonLiteInvariantChecker", ThreatLevel.HIGH, 0.8, {}, 1.0),
        ]
        signal = self.aggregator.aggregate(results)
        self.assertGreater(signal.final_score, 0.3)
        self.assertNotEqual(signal.recommended_action, "none")

    def test_signal_serialization(self):
        """ThreatSignal JSON 직렬화"""
        results = [
            EngineResult("E1", ThreatLevel.HIGH, 0.8, {"test": True}, 2.5),
        ]
        signal = self.aggregator.aggregate(results, {"from": "0xTest", "amount": 1000})
        d = signal.to_dict()
        self.assertIn("signal_id", d)
        self.assertIn("engine_results", d)
        json_str = json.dumps(d)  # JSON 직렬화 가능 확인
        self.assertIsInstance(json_str, str)


# ═══════════════════════════════════════════════════════════════════════════
# E2E 파이프라인 테스트 (on-chain 제외)
# ═══════════════════════════════════════════════════════════════════════════

class TestPipelineE2E(unittest.TestCase):
    """전체 파이프라인 테스트 (on-chain TX 전송 제외)"""

    def setUp(self):
        self.engines = [
            SequenceAnomalyEngine(),
            FlashLoanRuleEngine(),
            HoustonLiteInvariantChecker(),
        ]
        self.aggregator = ThreatAggregator()

    def _run_pipeline(self, tx_data):
        results = [e.analyze(tx_data) for e in self.engines]
        return self.aggregator.aggregate(results, tx_data)

    def test_t1_full_pipeline_normal(self):
        """T1: 정상 소액 → 전체 파이프라인 none"""
        # 이력 쌓기
        for _ in range(5):
            self._run_pipeline({
                "from": "0xUser", "to": "0xRecv", "amount": 500, "type": "transfer",
                "call_sequence": ["transfer"],
                "state_before": {"total_supply": 1e6, "initial_supply": 1e6,
                                 "reserve": 5e5, "price": 1.0, "mint_limit": 5e5},
                "state_after": {"total_supply": 1e6, "reserve": 5e5, "price": 1.0,
                                "period_mint_amount": 0},
            })

        signal = self._run_pipeline({
            "from": "0xUser", "to": "0xRecv", "amount": 500, "type": "transfer",
            "call_sequence": ["transfer"],
            "state_before": {"total_supply": 1e6, "initial_supply": 1e6,
                             "reserve": 5e5, "price": 1.0, "mint_limit": 5e5},
            "state_after": {"total_supply": 1e6, "reserve": 5e5, "price": 1.0,
                            "period_mint_amount": 0},
        })
        self.assertEqual(signal.recommended_action, "none")

    def test_t3_full_pipeline_mint_attack(self):
        """T3: 대량 민트 공격 → pause_macro"""
        signal = self._run_pipeline({
            "from": "0xAttacker", "to": "0xAttacker", "amount": 5_000_000,
            "type": "mint",
            "call_sequence": ["mint", "mint", "transfer"],
            "state_before": {"total_supply": 1_000_000, "initial_supply": 1_000_000,
                             "reserve": 500_000, "price": 1.0, "mint_limit": 500_000},
            "state_after": {"total_supply": 6_000_000, "reserve": 500_000,
                            "price": 0.7, "period_mint_amount": 5_000_000},
        })
        self.assertIn(signal.recommended_action, ["pause_macro", "pause_all"])
        self.assertGreater(signal.final_score, 0.5)

    def test_t4_full_pipeline_flash_loan(self):
        """T4: Flash Loan 공격 → pause_macro"""
        signal = self._run_pipeline({
            "from": "0xAttacker", "to": "0xProtocol", "amount": 10_000_000,
            "type": "flash_loan",
            "call_sequence": ["flashLoan", "swap", "manipulate", "repay"],
            "state_before": {"total_supply": 1e6, "initial_supply": 1e6,
                             "reserve": 5e5, "price": 1.0, "mint_limit": 5e5},
            "state_after": {"total_supply": 1e6, "reserve": 1e5,
                            "price": 0.3, "period_mint_amount": 0},
        })
        self.assertIn(signal.recommended_action, ["pause_macro", "pause_all"])

    def test_engine_info_completeness(self):
        """모든 엔진의 get_engine_info() 완전성 확인"""
        required_keys = {"name", "reference", "status", "real_integration_point"}
        for engine in self.engines:
            info = engine.get_engine_info()
            for key in required_keys:
                self.assertIn(key, info, f"{engine.name} missing key: {key}")


# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("FDS Watchtower Engine Tests")
    print("=" * 70)
    unittest.main(verbosity=2)
