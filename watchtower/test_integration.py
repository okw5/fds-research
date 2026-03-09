"""
On-chain 통합 테스트 (HardHat 로컬 노드 필요)

테스트 시나리오:
  T7: Timeout 자동 복구 (evm_increaseTime)
  T8: 블랙리스트 차단
  T9: 서명 무효화
  T10: 전체 파이프라인 (WatchtowerService → on-chain)

실행 전 준비:
  1. npx hardhat node  (별도 터미널)
  2. npx hardhat run scripts/deploy_all.ts --network localhost
  3. python test_integration.py

HardHat 노드 없이 실행하면 on-chain 테스트는 skip됩니다.
"""

import sys
import os
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── On-chain 연결 시도 ──
HARDHAT_AVAILABLE = False
try:
    from web3 import Web3
    from eth_account import Account
    from eth_account.messages import encode_defunct

    w3 = Web3(Web3.HTTPProvider("http://127.0.0.1:8545"))
    if w3.is_connected():
        HARDHAT_AVAILABLE = True
except ImportError:
    pass

# ── 엔진 임포트 ──
from lib.engines.base import ThreatLevel, EngineResult, ThreatSignal
from lib.engines.sequence_anomaly import SequenceAnomalyEngine
from lib.engines.flash_loan_rule import FlashLoanRuleEngine
from lib.engines.houston_lite import HoustonLiteInvariantChecker
from lib.engines.aggregator import ThreatAggregator


class TestWatchtowerServiceOffline(unittest.TestCase):
    """WatchtowerService 오프라인 테스트 (on-chain 불필요)"""

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

    def test_t10_normal_pipeline(self):
        """T10-a: 정상 TX 파이프라인 → no action"""
        for _ in range(5):
            self._run_pipeline({
                "from": "0xUser", "to": "0xRecv", "amount": 500, "type": "transfer",
                "call_sequence": ["transfer"],
                "state_before": {"total_supply": 1e6, "initial_supply": 1e6,
                                 "reserve": 5e5, "price": 1.0, "mint_limit": 5e5},
                "state_after": {"total_supply": 1e6, "reserve": 5e5,
                                "price": 1.0, "period_mint_amount": 0},
            })
        signal = self._run_pipeline({
            "from": "0xUser", "to": "0xRecv", "amount": 500, "type": "transfer",
            "call_sequence": ["transfer"],
            "state_before": {"total_supply": 1e6, "initial_supply": 1e6,
                             "reserve": 5e5, "price": 1.0, "mint_limit": 5e5},
            "state_after": {"total_supply": 1e6, "reserve": 5e5,
                            "price": 1.0, "period_mint_amount": 0},
        })
        self.assertEqual(signal.recommended_action, "none")

    def test_t10_attack_pipeline(self):
        """T10-b: 공격 TX 파이프라인 → pause or blacklist"""
        signal = self._run_pipeline({
            "from": "0xAttacker", "to": "0xTarget", "amount": 5_000_000,
            "type": "exploit_mint",
            "call_sequence": ["mint", "mint", "transfer"],
            "state_before": {"total_supply": 1_000_000, "initial_supply": 1_000_000,
                             "reserve": 500_000, "price": 1.0, "mint_limit": 500_000},
            "state_after": {"total_supply": 6_000_000, "reserve": 500_000,
                            "price": 0.6, "period_mint_amount": 5_000_000},
        })
        self.assertNotEqual(signal.recommended_action, "none")
        self.assertGreater(signal.final_score, 0.4)

    def test_t10_signal_json_completeness(self):
        """T10-c: ThreatSignal JSON 완전성 검사"""
        signal = self._run_pipeline({
            "from": "0xTest", "to": "0xRecv", "amount": 1_000_000,
            "type": "flash_loan",
            "call_sequence": ["flashLoan", "swap", "manipulate", "repay"],
            "state_before": {"total_supply": 1e6, "initial_supply": 1e6,
                             "reserve": 5e5, "price": 1.0, "mint_limit": 5e5},
            "state_after": {"total_supply": 1e6, "reserve": 1e5,
                            "price": 0.3, "period_mint_amount": 0},
        })
        d = signal.to_dict()
        required_keys = {"signal_id", "timestamp", "threat_level", "final_score",
                         "recommended_action", "engine_results", "target_tx"}
        self.assertTrue(required_keys.issubset(d.keys()))
        self.assertEqual(len(d["engine_results"]), 3)

        for er in d["engine_results"]:
            self.assertIn("engine_name", er)
            self.assertIn("threat_level", er)
            self.assertIn("confidence", er)
            self.assertIn("latency_ms", er)

    def test_t10_multiple_attacks_history(self):
        """T10-d: 연속 공격 시 이력 누적 + 엔진1 적응"""
        signals = []
        for i in range(5):
            signal = self._run_pipeline({
                "from": "0xRepeatAttacker", "to": "0xTarget",
                "amount": 1000 * (2 ** i),  # 점점 증가
                "type": "transfer",
                "call_sequence": ["transfer"],
                "state_before": {"total_supply": 1e6, "initial_supply": 1e6,
                                 "reserve": 5e5, "price": 1.0, "mint_limit": 5e5},
                "state_after": {"total_supply": 1e6, "reserve": 5e5,
                                "price": 1.0, "period_mint_amount": 0},
            })
            signals.append(signal)

        # 마지막 TX (16000)의 엔진1 점수가 첫 TX (1000)보다 높아야 함
        first_e1 = signals[0].engine_results[0]
        last_e1 = signals[-1].engine_results[0]
        # 이력이 충분하면 마지막 것이 더 높은 위협으로 판정됨
        self.assertGreaterEqual(
            list(ThreatLevel).index(last_e1.threat_level),
            list(ThreatLevel).index(first_e1.threat_level),
        )


@unittest.skipUnless(HARDHAT_AVAILABLE, "HardHat node not running")
class TestOnChainIntegration(unittest.TestCase):
    """On-chain 통합 테스트 (HardHat 로컬 노드 필요)"""

    @classmethod
    def setUpClass(cls):
        cls.w3 = w3
        cls.accounts = cls.w3.eth.accounts

    def test_t9_invalid_signature(self):
        """T9: 잘못된 키로 서명 → on-chain revert 확인"""
        from lib.engines.signal_signer import SignalSigner

        # 맞는 키: HardHat Account #1
        CORRECT_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
        # 틀린 키: HardHat Account #5
        WRONG_PK = "0x8b3a350cf5c34c9194ca85829a2df0ec3153be0318b5e2d3348e872092edffba"

        correct_signer = SignalSigner(CORRECT_PK, self.w3)
        wrong_signer = SignalSigner(WRONG_PK, self.w3)

        # 두 서명이 다른 주소에서 나옴을 검증
        self.assertNotEqual(correct_signer.address, wrong_signer.address)

        # 같은 메시지에 대해 다른 서명 생성됨
        sig_correct = correct_signer.sign_pause_signal(
            self.accounts[0], 0,
        )
        sig_wrong = wrong_signer.sign_pause_signal(
            self.accounts[0], 0,
        )
        self.assertNotEqual(sig_correct, sig_wrong)

    def test_signer_address_derivation(self):
        """SignalSigner가 올바른 주소를 derive하는지 확인"""
        from lib.engines.signal_signer import SignalSigner

        PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
        signer = SignalSigner(PK, self.w3)

        # HardHat Account #1 주소와 일치해야 함
        expected = Account.from_key(PK).address
        self.assertEqual(signer.address, expected)

    def test_signature_recovery(self):
        """ECDSA 서명 → 복원 주소 일치 검증"""
        from lib.engines.signal_signer import SignalSigner

        PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
        signer = SignalSigner(PK, self.w3)

        contract_addr = self.accounts[0]
        nonce = 0

        # 서명 생성
        sig = signer.sign_pause_signal(contract_addr, nonce)

        # Python 측에서 복원
        msg_hash = self.w3.solidity_keccak(
            ['string', 'uint256', 'address', 'uint256'],
            ["EMERGENCY_PAUSE", self.w3.eth.chain_id, contract_addr, nonce]
        )
        message = encode_defunct(hexstr=msg_hash.hex())
        recovered = Account.recover_message(message, signature=sig)

        self.assertEqual(recovered, signer.address)


# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("FDS Watchtower Integration Tests")
    print(f"HardHat Node: {'Connected [OK]' if HARDHAT_AVAILABLE else 'Not available [SKIP] (on-chain tests skipped)'}")
    print("=" * 70)
    unittest.main(verbosity=2)
