"""
Scenario 데이터 클래스 정의
실험에 사용될 공격/정상 시나리오의 표준 데이터 구조
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
import uuid


class ScenarioLabel(Enum):
    """시나리오 레이블 (Ground Truth)"""
    ATTACK = "ATTACK"
    NORMAL = "NORMAL"


class ScenarioType(Enum):
    """시나리오 유형 상세"""
    # 공격 유형
    INFINITE_MINT = "infinite_mint"           # 대량 민트 공격
    RESERVE_DRAIN = "reserve_drain"           # 금고 탈취
    FLASH_LOAN_DEPEG = "flash_loan_depeg"     # 플래시론 디페깅
    THRESHOLD_EVASION = "threshold_evasion"   # 임계값 회피 공격
    SYBIL_ATTACK = "sybil_attack"             # 분산 공격 (다중 지갑)
    GRADUAL_ESCALATION = "gradual_escalation" # 점진적 증가 공격
    CAMOUFLAGE = "camouflage"                 # 정상 위장 공격
    SANDWICH_ATTACK = "sandwich_attack"         # 샌드위치 공격 (DEX 가격 조작)
    
    # 정상 유형
    NORMAL_TRANSFER = "normal_transfer"       # 일반 송금
    LARGE_TRANSFER = "large_transfer"         # 대량 정상 송금
    LIQUIDITY_ADD = "liquidity_add"           # 유동성 공급
    BATCH_PAYMENT = "batch_payment"           # 급여/배당 지급
    NORMAL_MINT = "normal_mint"               # 정상적 발행 (담보 기반)
    NORMAL_FLASH_LOAN = "normal_flash_loan"   # 정상 플래시론 (차익거래, 화이트리스트)


@dataclass
class Scenario:
    """
    실험용 시나리오 데이터 클래스
    
    Attributes:
        id: 고유 식별자
        label: Ground Truth (ATTACK or NORMAL)
        scenario_type: 시나리오 세부 유형
        name: 사람이 읽기 쉬운 이름
        description: 시나리오 설명
        parameters: 시나리오별 파라미터 (금액, 횟수 등)
        network_condition: 네트워크 상태 (normal, congested, severe)
        expected_detection: 예상 탐지 여부 (테스트용)
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    label: ScenarioLabel = ScenarioLabel.NORMAL
    scenario_type: ScenarioType = ScenarioType.NORMAL_TRANSFER
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    network_condition: str = "normal"  # normal, congested, severe
    expected_detection: Optional[bool] = None
    
    def __post_init__(self):
        if not self.name:
            self.name = f"{self.scenario_type.value}_{self.id}"
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'id': self.id,
            'label': self.label.value,
            'scenario_type': self.scenario_type.value,
            'name': self.name,
            'description': self.description,
            'parameters': self.parameters,
            'network_condition': self.network_condition,
            'expected_detection': self.expected_detection
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Scenario':
        """딕셔너리에서 생성"""
        return cls(
            id=data.get('id', str(uuid.uuid4())[:8]),
            label=ScenarioLabel(data.get('label', 'NORMAL')),
            scenario_type=ScenarioType(data.get('scenario_type', 'normal_transfer')),
            name=data.get('name', ''),
            description=data.get('description', ''),
            parameters=data.get('parameters', {}),
            network_condition=data.get('network_condition', 'normal'),
            expected_detection=data.get('expected_detection')
        )
    
    def is_attack(self) -> bool:
        """공격 시나리오 여부"""
        return self.label == ScenarioLabel.ATTACK
    
    def get_amount(self) -> float:
        """파라미터에서 금액 추출"""
        return self.parameters.get('amount', 0)
    
    def get_gas_price(self) -> int:
        """네트워크 상태에 따른 Gas Price 반환 (Gwei)"""
        gas_prices = {
            'normal': 50,
            'congested': 300,
            'severe': 500
        }
        return gas_prices.get(self.network_condition, 50)


# 시나리오 유형별 레이블 매핑
ATTACK_TYPES = {
    ScenarioType.INFINITE_MINT,
    ScenarioType.RESERVE_DRAIN,
    ScenarioType.FLASH_LOAN_DEPEG,
    ScenarioType.THRESHOLD_EVASION,
    ScenarioType.SYBIL_ATTACK,
    ScenarioType.GRADUAL_ESCALATION,
    ScenarioType.CAMOUFLAGE,
    ScenarioType.SANDWICH_ATTACK
}

NORMAL_TYPES = {
    ScenarioType.NORMAL_TRANSFER,
    ScenarioType.LARGE_TRANSFER,
    ScenarioType.LIQUIDITY_ADD,
    ScenarioType.BATCH_PAYMENT,
    ScenarioType.NORMAL_MINT,
    ScenarioType.NORMAL_FLASH_LOAN,
}


def get_label_for_type(scenario_type: ScenarioType) -> ScenarioLabel:
    """시나리오 유형에 대한 레이블 반환"""
    if scenario_type in ATTACK_TYPES:
        return ScenarioLabel.ATTACK
    return ScenarioLabel.NORMAL
