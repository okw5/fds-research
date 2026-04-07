"""
Contract Analyzer — 실제 스마트 컨트랙트 코드를 정적 분석하여
취약점/악성 패턴 Feature를 추출하고 레이블이 포함된 벤치마크 시나리오를 생성합니다.

sample_data/sample_data/positive samples  → Label: ATTACK  (악성 컨트랙트)
sample_data/sample_data/negative samples  → Label: NORMAL  (정상 컨트랙트)
"""

import os
import re
import json
import hashlib
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple

# 조건부 임포트
try:
    from .scenario import Scenario, ScenarioLabel, ScenarioType
except ImportError:
    from scenario import Scenario, ScenarioLabel, ScenarioType


# ──────────────────────────────────────────────────────────────────────
#  Feature Extraction Patterns
# ──────────────────────────────────────────────────────────────────────

# 악성 패턴 (positive indicators for ATTACK)
MALICIOUS_PATTERNS: Dict[str, re.Pattern] = {
    # 숨겨진 세금/수수료 구조
    "hidden_fee": re.compile(
        r"(?:_initialBuyTax|_initialSellTax|_transferTax|taxAmount|_taxWallet"
        r"|buyTax|sellTax|feeOnBuy|feeOnSell)\s*[=;]",
        re.IGNORECASE,
    ),
    # 매매 제한 (허니팟 패턴)
    "trading_lock": re.compile(
        r"(?:tradingOpen|tradingEnabled|tradingActive|canTrade)\s*[=;]",
        re.IGNORECASE,
    ),
    # 최대 보유/거래 한도
    "max_wallet_limit": re.compile(
        r"(?:_maxTxAmount|_maxWalletSize|maxTransaction|maxWallet)",
        re.IGNORECASE,
    ),
    # 블랙리스트/블록 매커니즘
    "blacklist": re.compile(
        r"(?:isBlacklisted|_isBlackListed|blacklist|bots\[|isBot\[)",
        re.IGNORECASE,
    ),
    # 수수료 스왑 기능
    "swap_fee_mechanism": re.compile(
        r"swapTokensForEth|swapExactTokensForETH|sendETHToFee",
        re.IGNORECASE,
    ),
    # Uniswap 라우터 하드코딩 (보통 밈/스캠 토큰)
    "hardcoded_router": re.compile(
        r"0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        re.IGNORECASE,
    ),
    # 오너 전용 거래 활성화
    "owner_trading_control": re.compile(
        r"function\s+(?:openTrading|enableTrading|startTrading)",
        re.IGNORECASE,
    ),
    # 직접 민트 (제한 없는)
    "unrestricted_mint": re.compile(
        r"function\s+(?:mint|_mint)\s*\([^)]*\)(?:(?!onlyOwner|require|_msgSender).)*\{",
        re.IGNORECASE | re.DOTALL,
    ),
    # 셀 카운터 (MEV/스나이퍼 방지 위장)
    "sell_counter": re.compile(
        r"(?:sellCount|lastSellBlock|_preventSwapBefore|_reduceBuyTaxAt)",
        re.IGNORECASE,
    ),
    # tx.origin 사용 (보안 취약점)
    "tx_origin_usage": re.compile(
        r"tx\.origin",
    ),
}

# 정상 패턴 (positive indicators for NORMAL/legitimate)
LEGITIMATE_PATTERNS: Dict[str, re.Pattern] = {
    # 접근 제어 (OpenZeppelin 스타일)
    "access_control": re.compile(
        r"(?:onlyOwner|onlyGovernor|onlyAdmin|Ownable|AccessControl|onlyRole)",
        re.IGNORECASE,
    ),
    # 이벤트 로깅
    "event_logging": re.compile(
        r"event\s+\w+\s*\(",
    ),
    # 재진입 방지
    "reentrancy_guard": re.compile(
        r"(?:nonReentrant|ReentrancyGuard|reentrancyLock)",
        re.IGNORECASE,
    ),
    # 인터페이스/추상 구조 (설계 패턴)
    "interface_usage": re.compile(
        r"(?:interface\s+\w+|abstract\s+contract)",
        re.IGNORECASE,
    ),
    # ERC4626 볼트 패턴
    "erc4626_vault": re.compile(
        r"(?:IERC4626|convertToAssets|convertToShares|previewDeposit|previewRedeem)",
        re.IGNORECASE,
    ),
    # 오라클 통합
    "oracle_integration": re.compile(
        r"(?:PriceOracle|getQuote|oracle|AggregatorV3)",
        re.IGNORECASE,
    ),
    # 거버넌스 패턴
    "governance": re.compile(
        r"(?:governor|governance|proposal|vote|quorum)",
        re.IGNORECASE,
    ),
    # 팩토리 패턴
    "factory_pattern": re.compile(
        r"(?:GenericFactory|createProxy|deployMetaProxy)",
        re.IGNORECASE,
    ),
}


@dataclass
class ContractFeatures:
    """단일 컨트랙트에서 추출된 Feature 집합"""
    address: str
    filename: str
    label: str  # "ATTACK" or "NORMAL"
    solidity_version: str = ""
    contract_names: List[str] = field(default_factory=list)
    total_lines: int = 0
    total_bytes: int = 0

    # 악성 패턴 매칭 결과 (패턴명 → 매칭 횟수)
    malicious_hits: Dict[str, int] = field(default_factory=dict)
    # 정상 패턴 매칭 결과
    legitimate_hits: Dict[str, int] = field(default_factory=dict)

    # 파생 지표
    malicious_score: float = 0.0  # 악성 패턴 총 점수
    legitimate_score: float = 0.0  # 정상 패턴 총 점수
    risk_score: float = 0.0  # malicious - legitimate (높을수록 위험)

    # 코드 복잡도 관련
    function_count: int = 0
    modifier_count: int = 0
    external_call_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────
#  Contract Analyzer
# ──────────────────────────────────────────────────────────────────────

class ContractAnalyzer:
    """
    Solidity 컨트랙트 정적 분석기

    sample_data 폴더의 실제 컨트랙트를 분석하여
    Feature를 추출하고 벤치마크 시나리오로 변환합니다.
    """

    def __init__(self, sample_data_root: str):
        """
        Args:
            sample_data_root: sample_data/sample_data 경로
        """
        self.sample_data_root = sample_data_root
        self.positive_dir = os.path.join(sample_data_root, "positive samples")
        self.negative_dir = os.path.join(sample_data_root, "negative samples")
        self.features_cache: List[ContractFeatures] = []

    # ──────────────────────────────────────────────────────────────────
    #  Source Code Extraction
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_source(filepath: str) -> str:
        """
        .sol 파일에서 소스 코드를 추출합니다.
        일부 파일은 Etherscan JSON 포맷({{ ... }})으로 되어 있습니다.
        """
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            raw = f.read()

        # Etherscan JSON 포맷 감지 (이중 중괄호로 시작)
        stripped = raw.strip()
        if stripped.startswith("{{"):
            # 이중 중괄호 → 단일 중괄호로 정규화
            normalized = stripped[1:-1] if stripped.endswith("}}") else stripped[1:]
            try:
                data = json.loads(normalized)
                # sources 내의 모든 content를 합침
                if "sources" in data:
                    parts = []
                    for src_key, src_val in data["sources"].items():
                        if isinstance(src_val, dict) and "content" in src_val:
                            parts.append(src_val["content"])
                    return "\n".join(parts)
            except json.JSONDecodeError:
                pass

        # 일반 JSON 포맷 시도
        if stripped.startswith("{"):
            try:
                data = json.loads(stripped)
                if "sources" in data:
                    parts = []
                    for src_val in data["sources"].values():
                        if isinstance(src_val, dict) and "content" in src_val:
                            parts.append(src_val["content"])
                    return "\n".join(parts)
            except json.JSONDecodeError:
                pass

        # 순수 Solidity 코드
        return raw

    # ──────────────────────────────────────────────────────────────────
    #  Feature Extraction
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_solidity_version(source: str) -> str:
        match = re.search(r"pragma solidity\s+([^;]+);", source)
        return match.group(1).strip() if match else "unknown"

    @staticmethod
    def _extract_contract_names(source: str) -> List[str]:
        return re.findall(r"contract\s+(\w+)", source)

    @staticmethod
    def _count_functions(source: str) -> int:
        return len(re.findall(r"function\s+\w+\s*\(", source))

    @staticmethod
    def _count_modifiers(source: str) -> int:
        return len(re.findall(r"modifier\s+\w+", source))

    @staticmethod
    def _count_external_calls(source: str) -> int:
        return len(re.findall(r"\.\w+\s*\(", source))

    def analyze_contract(self, filepath: str, label: str) -> ContractFeatures:
        """단일 컨트랙트 분석"""
        filename = os.path.basename(filepath)
        address = filename.replace(".sol", "")

        source = self._extract_source(filepath)

        features = ContractFeatures(
            address=address,
            filename=filename,
            label=label,
            solidity_version=self._extract_solidity_version(source),
            contract_names=self._extract_contract_names(source),
            total_lines=source.count("\n") + 1,
            total_bytes=len(source.encode("utf-8")),
            function_count=self._count_functions(source),
            modifier_count=self._count_modifiers(source),
            external_call_count=self._count_external_calls(source),
        )

        # 악성 패턴 탐지
        for name, pattern in MALICIOUS_PATTERNS.items():
            hits = len(pattern.findall(source))
            if hits > 0:
                features.malicious_hits[name] = hits

        # 정상 패턴 탐지
        for name, pattern in LEGITIMATE_PATTERNS.items():
            hits = len(pattern.findall(source))
            if hits > 0:
                features.legitimate_hits[name] = hits

        # 점수 계산
        features.malicious_score = sum(features.malicious_hits.values())
        features.legitimate_score = sum(features.legitimate_hits.values())
        features.risk_score = features.malicious_score - features.legitimate_score

        return features

    def analyze_all(self) -> List[ContractFeatures]:
        """모든 sample 컨트랙트를 분석합니다."""
        results = []

        # Positive samples (ATTACK)
        if os.path.isdir(self.positive_dir):
            for fn in sorted(os.listdir(self.positive_dir)):
                if fn.endswith(".sol"):
                    path = os.path.join(self.positive_dir, fn)
                    features = self.analyze_contract(path, "ATTACK")
                    results.append(features)

        # Negative samples (NORMAL)
        if os.path.isdir(self.negative_dir):
            for fn in sorted(os.listdir(self.negative_dir)):
                if fn.endswith(".sol"):
                    path = os.path.join(self.negative_dir, fn)
                    features = self.analyze_contract(path, "NORMAL")
                    results.append(features)

        self.features_cache = results
        return results

    # ──────────────────────────────────────────────────────────────────
    #  Scenario Generation  — Feature → FDS Scenario 변환
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _classify_attack_type(features: ContractFeatures) -> ScenarioType:
        """악성 패턴에 따라 공격 유형을 분류합니다."""
        hits = features.malicious_hits

        if hits.get("unrestricted_mint", 0) > 0:
            return ScenarioType.INFINITE_MINT
        if hits.get("hidden_fee", 0) >= 3 and hits.get("swap_fee_mechanism", 0) > 0:
            return ScenarioType.RESERVE_DRAIN  # 사실상 세금 탈취
        if hits.get("trading_lock", 0) > 0 and hits.get("owner_trading_control", 0) > 0:
            return ScenarioType.THRESHOLD_EVASION  # 허니팟 = 임계값 회피와 유사
        if hits.get("sell_counter", 0) > 0:
            return ScenarioType.GRADUAL_ESCALATION
        if hits.get("blacklist", 0) > 0:
            return ScenarioType.SYBIL_ATTACK  # 선별적 차단은 시빌 방어 위장
        if hits.get("tx_origin_usage", 0) > 0:
            return ScenarioType.CAMOUFLAGE
        # 기본: 복합 공격
        return ScenarioType.THRESHOLD_EVASION

    @staticmethod
    def _classify_normal_type(features: ContractFeatures) -> ScenarioType:
        """정상 패턴에 따라 정상 유형을 분류합니다."""
        hits = features.legitimate_hits

        if hits.get("erc4626_vault", 0) > 0:
            return ScenarioType.LIQUIDITY_ADD
        if hits.get("factory_pattern", 0) > 0:
            return ScenarioType.BATCH_PAYMENT
        if hits.get("governance", 0) > 0:
            return ScenarioType.NORMAL_MINT  # 거버넌스 기반 발행
        return ScenarioType.NORMAL_TRANSFER

    def features_to_scenario(self, features: ContractFeatures) -> Scenario:
        """ContractFeatures를 FDS Scenario 객체로 변환합니다."""
        # 해시 기반 고유 ID
        uid = hashlib.sha256(features.address.encode()).hexdigest()[:8]

        if features.label == "ATTACK":
            scenario_type = self._classify_attack_type(features)
            label = ScenarioLabel.ATTACK

            # 위험도에 따른 금액 파라미터 매핑
            base_amount = int(10_000 * (1 + features.risk_score))
            amount = max(10_000, min(50_000_000, base_amount))

            top_patterns = ", ".join(
                sorted(features.malicious_hits, key=features.malicious_hits.get, reverse=True)[:3]
            )
            description = (
                f"[실제 컨트랙트 {features.address[:10]}...] "
                f"악성 패턴 탐지: {top_patterns} "
                f"(risk_score={features.risk_score:.1f})"
            )
        else:
            scenario_type = self._classify_normal_type(features)
            label = ScenarioLabel.NORMAL
            amount = max(100, min(100_000, int(1000 * (1 + features.legitimate_score * 0.1))))

            top_patterns = ", ".join(
                sorted(features.legitimate_hits, key=features.legitimate_hits.get, reverse=True)[:3]
            )
            description = (
                f"[실제 컨트랙트 {features.address[:10]}...] "
                f"정상 패턴: {top_patterns} "
                f"(legitimate_score={features.legitimate_score:.0f})"
            )

        return Scenario(
            id=uid,
            label=label,
            scenario_type=scenario_type,
            name=f"RealContract_{features.address[:10]}",
            description=description,
            parameters={
                "amount": amount,
                "source_address": features.address,
                "source_file": features.filename,
                "solidity_version": features.solidity_version,
                "contract_names": features.contract_names[:3],
                "malicious_hits": features.malicious_hits,
                "legitimate_hits": features.legitimate_hits,
                "malicious_score": features.malicious_score,
                "legitimate_score": features.legitimate_score,
                "risk_score": features.risk_score,
                "function_count": features.function_count,
                "total_lines": features.total_lines,
                "is_real_contract": True,
            },
            network_condition="normal",
            expected_detection=(features.label == "ATTACK"),
        )

    def generate_dataset(self) -> List[Scenario]:
        """전체 sample_data를 분석하여 Scenario 리스트로 반환합니다."""
        all_features = self.analyze_all()
        return [self.features_to_scenario(f) for f in all_features]

    # ──────────────────────────────────────────────────────────────────
    #  Export
    # ──────────────────────────────────────────────────────────────────

    def export_features_json(self, output_path: str):
        """Feature 분석 결과를 JSON으로 저장합니다."""
        if not self.features_cache:
            self.analyze_all()
        data = [f.to_dict() for f in self.features_cache]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[ContractAnalyzer] Features exported → {output_path} ({len(data)} contracts)")

    def export_dataset_json(self, output_path: str):
        """벤치마크 데이터셋을 JSON으로 저장합니다."""
        scenarios = self.generate_dataset()
        data = [s.to_dict() for s in scenarios]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"[ContractAnalyzer] Dataset exported → {output_path} ({len(data)} scenarios)")

    def print_summary(self):
        """분석 요약을 출력합니다."""
        if not self.features_cache:
            self.analyze_all()

        attacks = [f for f in self.features_cache if f.label == "ATTACK"]
        normals = [f for f in self.features_cache if f.label == "NORMAL"]

        print("=" * 60)
        print("  Contract Analysis Summary")
        print("=" * 60)
        print(f"  Total contracts analyzed: {len(self.features_cache)}")
        print(f"    Positive (ATTACK) : {len(attacks)}")
        print(f"    Negative (NORMAL) : {len(normals)}")
        print()

        if attacks:
            avg_risk = sum(f.risk_score for f in attacks) / len(attacks)
            all_mal = {}
            for f in attacks:
                for k, v in f.malicious_hits.items():
                    all_mal[k] = all_mal.get(k, 0) + v
            top3 = sorted(all_mal.items(), key=lambda x: -x[1])[:5]
            print(f"  [ATTACK] avg risk_score: {avg_risk:.1f}")
            print(f"  [ATTACK] top malicious patterns:")
            for name, count in top3:
                print(f"    - {name}: {count}")

        if normals:
            avg_legit = sum(f.legitimate_score for f in normals) / len(normals)
            all_leg = {}
            for f in normals:
                for k, v in f.legitimate_hits.items():
                    all_leg[k] = all_leg.get(k, 0) + v
            top3 = sorted(all_leg.items(), key=lambda x: -x[1])[:5]
            print(f"\n  [NORMAL] avg legitimate_score: {avg_legit:.1f}")
            print(f"  [NORMAL] top legitimate patterns:")
            for name, count in top3:
                print(f"    - {name}: {count}")
        print("=" * 60)


# ──────────────────────────────────────────────────────────────────────
#  CLI Entry Point
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # 프로젝트 루트 기준
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    sample_root = os.path.join(project_root, "sample_data", "sample_data")

    analyzer = ContractAnalyzer(sample_root)
    analyzer.print_summary()

    # 결과 내보내기
    output_dir = os.path.join(project_root, "sample_data")
    analyzer.export_features_json(os.path.join(output_dir, "analysis_features.json"))
    analyzer.export_dataset_json(os.path.join(output_dir, "real_contract_dataset.json"))
