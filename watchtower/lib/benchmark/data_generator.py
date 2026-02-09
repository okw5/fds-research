"""
BenchmarkDataGenerator
레이블이 포함된 벤치마크 테스트 데이터 생성
"""

import random
from typing import List, Dict, Any, Optional

# 조건부 임포트: 패키지 모드와 직접 실행 모드 지원
try:
    from .scenario import (
        Scenario, ScenarioType, ScenarioLabel, 
        get_label_for_type, ATTACK_TYPES, NORMAL_TYPES
    )
except ImportError:
    from scenario import (
        Scenario, ScenarioType, ScenarioLabel, 
        get_label_for_type, ATTACK_TYPES, NORMAL_TYPES
    )


class BenchmarkDataGenerator:
    """
    벤치마크 테스트 데이터 생성기
    
    공격과 정상 시나리오를 생성하여 Ground Truth 레이블이 포함된 데이터셋 제공
    """
    
    # 기본 임계값 설정 (실험 설계 문서 기반)
    DEFAULT_THRESHOLDS = {
        'mint_threshold': 10000,      # 총 발행량의 1%
        'drain_threshold': 0.10,      # Vault 잔액의 10%
        'depeg_threshold': 0.05,      # 5% 가격 괴리
        'micro_limit': 1000000,       # 소액 한도 (100만)
        'macro_threshold': 1000,      # 거액 임계값
    }
    
    def __init__(self, seed: Optional[int] = None):
        """
        Args:
            seed: 랜덤 시드 (재현성을 위해)
        """
        if seed is not None:
            random.seed(seed)
        self.thresholds = self.DEFAULT_THRESHOLDS.copy()
    
    def set_thresholds(self, thresholds: Dict[str, Any]):
        """임계값 설정 업데이트"""
        self.thresholds.update(thresholds)
    
    # =========================================================================
    # 공격 시나리오 생성
    # =========================================================================
    
    def generate_infinite_mint_attack(self, 
                                      amount_range: tuple = (50000, 500000),
                                      network: str = "normal") -> Scenario:
        """무한 민트 공격 시나리오 생성"""
        amount = random.randint(*amount_range)
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.INFINITE_MINT,
            name="대량 민트 공격",
            description=f"{amount:,} 토큰 불법 발행 시도",
            parameters={
                'amount': amount,
                'method': 'direct_mint',
                'blocks': 1
            },
            network_condition=network,
            expected_detection=True
        )
    
    def generate_reserve_drain_attack(self,
                                      amount_range: tuple = (1000, 5000),
                                      network: str = "normal") -> Scenario:
        """금고 탈취 공격 시나리오 생성"""
        amount = random.randint(*amount_range)
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.RESERVE_DRAIN,
            name="준비금 탈취 공격",
            description=f"{amount:,} ETH 불법 인출 시도",
            parameters={
                'amount': amount,
                'method': 'vault_exploit',
                'target': 'vault'
            },
            network_condition=network,
            expected_detection=True
        )
    
    def generate_flash_loan_attack(self,
                                   loan_range: tuple = (10_000_000, 100_000_000),
                                   network: str = "normal") -> Scenario:
        """플래시론 디페깅 공격 시나리오 생성"""
        loan_amount = random.randint(*loan_range)
        # 론 규모에 따른 예상 디페그 정도 계산
        depeg_percent = min(35, 8 + (loan_amount / 10_000_000) * 3)
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.FLASH_LOAN_DEPEG,
            name="플래시론 가격 조작",
            description=f"${loan_amount:,} USDC 플래시론으로 {depeg_percent:.1f}% 디페그 유도",
            parameters={
                'loan_amount': loan_amount,
                'expected_depeg': depeg_percent,
                'method': 'dex_manipulation'
            },
            network_condition=network,
            expected_detection=True
        )
    
    def generate_threshold_evasion_attack(self,
                                          evasion_ratio: float = 0.95,
                                          blocks: int = 10,
                                          network: str = "normal") -> Scenario:
        """임계값 회피 공격 시나리오 생성"""
        threshold = self.thresholds['mint_threshold']
        amount_per_block = int(threshold * evasion_ratio)
        total_amount = amount_per_block * blocks
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.THRESHOLD_EVASION,
            name="임계값 회피 공격",
            description=f"블록당 {amount_per_block:,} (임계값의 {evasion_ratio*100:.0f}%), {blocks}블록에 걸쳐 총 {total_amount:,} 탈취 시도",
            parameters={
                'amount_per_block': amount_per_block,
                'total_amount': total_amount,
                'blocks': blocks,
                'evasion_ratio': evasion_ratio
            },
            network_condition=network,
            expected_detection=True  # 누적 탐지로 잡아야 함
        )
    
    def generate_sybil_attack(self,
                              wallet_count: int = 10,
                              amount_per_wallet: int = 5000,
                              network: str = "normal") -> Scenario:
        """분산 공격 (Sybil Attack) 시나리오 생성"""
        total_amount = wallet_count * amount_per_wallet
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.SYBIL_ATTACK,
            name="분산 공격 (Sybil)",
            description=f"{wallet_count}개 지갑이 각각 {amount_per_wallet:,} 토큰 발행, 총 {total_amount:,}",
            parameters={
                'wallet_count': wallet_count,
                'amount_per_wallet': amount_per_wallet,
                'total_amount': total_amount
            },
            network_condition=network,
            expected_detection=True  # 전체 발행량 모니터링으로 탐지
        )
    
    def generate_gradual_escalation_attack(self,
                                           start_amount: int = 1000,
                                           multiplier: float = 2.0,
                                           blocks: int = 5,
                                           network: str = "normal") -> Scenario:
        """점진적 증가 공격 시나리오 생성"""
        amounts = [int(start_amount * (multiplier ** i)) for i in range(blocks)]
        total = sum(amounts)
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.GRADUAL_ESCALATION,
            name="점진적 증가 공격",
            description=f"블록별 발행: {amounts}, 총 {total:,}",
            parameters={
                'start_amount': start_amount,
                'multiplier': multiplier,
                'blocks': blocks,
                'amounts': amounts,
                'total_amount': total
            },
            network_condition=network,
            expected_detection=True  # 변화율 탐지 필요
        )
    
    def generate_camouflage_attack(self,
                                   normal_avg: int = 500,
                                   attack_increment: int = 200,
                                   blocks: int = 100,
                                   network: str = "normal") -> Scenario:
        """정상 위장 공격 시나리오 생성"""
        amount_per_block = normal_avg + attack_increment
        total = amount_per_block * blocks
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.CAMOUFLAGE,
            name="정상 위장 공격",
            description=f"정상 범위({normal_avg})에서 {attack_increment} 추가하여 {blocks}블록 동안 {total:,} 탈취",
            parameters={
                'normal_avg': normal_avg,
                'attack_increment': attack_increment,
                'amount_per_block': amount_per_block,
                'blocks': blocks,
                'total_amount': total
            },
            network_condition=network,
            expected_detection=False  # 이상 탐지(anomaly detection) 필요
        )
    
    # =========================================================================
    # 정상 시나리오 생성
    # =========================================================================
    
    def generate_normal_transfer(self,
                                 amount_range: tuple = (100, 10000),
                                 network: str = "normal") -> Scenario:
        """일반 송금 시나리오 생성"""
        amount = random.randint(*amount_range)
        return Scenario(
            label=ScenarioLabel.NORMAL,
            scenario_type=ScenarioType.NORMAL_TRANSFER,
            name="일반 송금",
            description=f"{amount:,} 토큰 정상 전송",
            parameters={
                'amount': amount,
                'method': 'transfer'
            },
            network_condition=network,
            expected_detection=False
        )
    
    def generate_large_transfer(self,
                                amount_range: tuple = (7000, 9000),
                                network: str = "normal") -> Scenario:
        """대량 정상 송금 (임계값 근접) 시나리오 생성"""
        amount = random.randint(*amount_range)
        return Scenario(
            label=ScenarioLabel.NORMAL,
            scenario_type=ScenarioType.LARGE_TRANSFER,
            name="대량 정상 송금",
            description=f"{amount:,} 토큰 정상 대량 전송 (임계값 근접)",
            parameters={
                'amount': amount,
                'method': 'transfer',
                'is_verified': True
            },
            network_condition=network,
            expected_detection=False
        )
    
    def generate_liquidity_add(self,
                               amount_range: tuple = (30000, 100000),
                               network: str = "normal") -> Scenario:
        """유동성 공급 시나리오 생성"""
        amount = random.randint(*amount_range)
        return Scenario(
            label=ScenarioLabel.NORMAL,
            scenario_type=ScenarioType.LIQUIDITY_ADD,
            name="유동성 공급",
            description=f"{amount:,} 토큰 정상 유동성 공급 (사전 승인됨)",
            parameters={
                'amount': amount,
                'method': 'addLiquidity',
                'is_whitelisted': True
            },
            network_condition=network,
            expected_detection=False
        )
    
    def generate_batch_payment(self,
                               recipient_count: int = 100,
                               amount_per_recipient: int = 500,
                               network: str = "normal") -> Scenario:
        """급여/배당 지급 시나리오 생성"""
        total = recipient_count * amount_per_recipient
        return Scenario(
            label=ScenarioLabel.NORMAL,
            scenario_type=ScenarioType.BATCH_PAYMENT,
            name="배치 지급",
            description=f"{recipient_count}명에게 각 {amount_per_recipient:,} 토큰, 총 {total:,}",
            parameters={
                'recipient_count': recipient_count,
                'amount_per_recipient': amount_per_recipient,
                'total_amount': total,
                'method': 'batch_transfer'
            },
            network_condition=network,
            expected_detection=False
        )
    
    def generate_normal_mint(self,
                             amount_range: tuple = (1000, 5000),
                             network: str = "normal") -> Scenario:
        """정상적 발행 (담보 기반) 시나리오 생성"""
        amount = random.randint(*amount_range)
        return Scenario(
            label=ScenarioLabel.NORMAL,
            scenario_type=ScenarioType.NORMAL_MINT,
            name="정상 발행",
            description=f"{amount:,} 토큰 정상 발행 (담보 검증 완료)",
            parameters={
                'amount': amount,
                'method': 'mint',
                'collateral_verified': True
            },
            network_condition=network,
            expected_detection=False
        )
    
    # =========================================================================
    # 데이터셋 생성
    # =========================================================================
    
    def generate_attack_scenarios(self, count: int, 
                                  network_mix: bool = False) -> List[Scenario]:
        """
        공격 시나리오 생성
        
        Args:
            count: 생성할 시나리오 수
            network_mix: True면 다양한 네트워크 상태 혼합
        """
        scenarios = []
        attack_generators = [
            self.generate_infinite_mint_attack,
            self.generate_reserve_drain_attack,
            self.generate_flash_loan_attack,
            self.generate_threshold_evasion_attack,
            self.generate_sybil_attack,
            self.generate_gradual_escalation_attack,
        ]
        
        networks = ['normal'] if not network_mix else ['normal', 'congested', 'severe']
        
        for i in range(count):
            generator = random.choice(attack_generators)
            network = random.choice(networks)
            scenarios.append(generator(network=network))
        
        return scenarios
    
    def generate_normal_scenarios(self, count: int,
                                  network_mix: bool = False) -> List[Scenario]:
        """
        정상 시나리오 생성
        
        Args:
            count: 생성할 시나리오 수
            network_mix: True면 다양한 네트워크 상태 혼합
        """
        scenarios = []
        # 가중치 적용: 일반 송금이 가장 많음
        normal_generators = [
            (self.generate_normal_transfer, 4),
            (self.generate_large_transfer, 2),
            (self.generate_liquidity_add, 1),
            (self.generate_batch_payment, 1),
            (self.generate_normal_mint, 2),
        ]
        
        weighted_generators = []
        for gen, weight in normal_generators:
            weighted_generators.extend([gen] * weight)
        
        networks = ['normal'] if not network_mix else ['normal', 'congested', 'severe']
        
        for i in range(count):
            generator = random.choice(weighted_generators)
            network = random.choice(networks)
            scenarios.append(generator(network=network))
        
        return scenarios
    
    def get_mixed_dataset(self, 
                          total_count: int = 1000,
                          attack_ratio: float = 0.3,
                          network_mix: bool = True,
                          shuffle: bool = True) -> List[Scenario]:
        """
        공격과 정상이 섞인 데이터셋 반환
        
        Args:
            total_count: 총 시나리오 수
            attack_ratio: 공격 비율 (0.0 ~ 1.0)
            network_mix: 네트워크 상태 다양화
            shuffle: 셔플 여부
        """
        attack_count = int(total_count * attack_ratio)
        normal_count = total_count - attack_count
        
        attacks = self.generate_attack_scenarios(attack_count, network_mix)
        normals = self.generate_normal_scenarios(normal_count, network_mix)
        
        dataset = attacks + normals
        
        if shuffle:
            random.shuffle(dataset)
        
        return dataset
    
    def get_balanced_dataset(self, 
                             count_per_type: int = 50,
                             network_mix: bool = True) -> List[Scenario]:
        """
        각 유형별로 균등한 시나리오를 포함하는 데이터셋
        테스트 및 디버깅용
        """
        scenarios = []
        
        # 공격 시나리오
        networks = ['normal', 'congested', 'severe'] if network_mix else ['normal']
        
        for _ in range(count_per_type):
            for network in networks:
                scenarios.extend([
                    self.generate_infinite_mint_attack(network=network),
                    self.generate_reserve_drain_attack(network=network),
                    self.generate_flash_loan_attack(network=network),
                ])
        
        # 정상 시나리오
        for _ in range(count_per_type * 2):  # 정상이 더 많음
            for network in networks:
                scenarios.extend([
                    self.generate_normal_transfer(network=network),
                    self.generate_large_transfer(network=network),
                ])
        
        random.shuffle(scenarios)
        return scenarios
