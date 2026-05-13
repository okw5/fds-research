"""
BenchmarkDataGenerator
레이블이 포함된 벤치마크 테스트 데이터 생성
"""

import os
import json
import random
from typing import List, Dict, Any, Optional

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
    
    @staticmethod
    def _inject_state_mock(scenario: Scenario):
        """
        HoustonLite 엔진(Engine3)에서 검사할 수 있도록, 트랜잭션 타입과 금액을 바탕으로
        가상의 state_before, state_after 딕셔너리를 생성하여 parameters에 주입합니다.
        """
        # 기준 상태
        initial_supply = 10_000_000
        current_supply = 15_000_000
        reserve = 2_000_000
        price = 1.0
        # collateral: current_supply 기반 120% (정상 담보 상태)
        # ※ initial_supply 기준이면 12M < current_supply 15M → 시작부터 위반 발생
        collateral = current_supply * 1.20

        state_before = {
            'total_supply': current_supply,
            'initial_supply': initial_supply,
            'reserve': reserve,
            'price': price,
            'mint_limit': 1_000_000,
            'period_mint_amount': 500_000,
            'collateral': collateral,          # [INV-8] 담보 총량 추가
            'is_sender_blacklisted': False
        }
        state_after = state_before.copy()

        # 시나리오별 amount 추출
        params = scenario.parameters
        amount = float(params.get('amount',
                 params.get('amount_per_block',
                 params.get('amount_per_wallet',
                 params.get('total_amount',
                 params.get('loan_amount', 0))))))

        # state_after 변화 모사 (Post-execution State Check 기반)
        stype = scenario.scenario_type
        if stype == ScenarioType.INFINITE_MINT:
            # 무담보 발행: totalSupply 증가 / collateral 불변 → INV-8 위반
            state_after['total_supply'] += amount
            state_after['period_mint_amount'] += amount
            state_after['price'] = max(0.01, price * (current_supply / state_after['total_supply']))
            # collateral은 변화 없음 (→ INV-8: collateral 부족 자동 위반)
        elif stype == ScenarioType.RESERVE_DRAIN:
            # 준비금 탈취: reserve 소진 + collateral 일부 감소 → INV-3/4 위반
            state_after['reserve'] = max(0, reserve - amount)
            state_after['collateral'] = max(0, collateral - amount * 0.5)
        elif stype == ScenarioType.FLASH_LOAN_DEPEG:
            # 플래시론 가격 조작: 가격 급락 → INV-6 위반
            expected_depeg = params.get('expected_depeg', 20) / 100.0
            state_after['price'] = price * (1.0 - expected_depeg)
        elif stype in (ScenarioType.NORMAL_TRANSFER, ScenarioType.LARGE_TRANSFER):
            # 정상 전송: 상태 변화 미미
            pass
        elif stype == ScenarioType.NORMAL_MINT:
            # 정상 발행: totalSupply + collateral 비례 증가 → 위반 없음
            state_after['total_supply'] += amount
            state_after['period_mint_amount'] += amount
            state_after['collateral'] = collateral + amount * 1.05  # 담보 초과 보유
        elif stype == ScenarioType.NORMAL_FLASH_LOAN:
            # 정상 플래시론: 미미한 가격 변화 (< 5%)
            state_after['price'] = price * 0.98

        params['state_before'] = state_before
        params['state_after'] = state_after



    def generate_infinite_mint_attack(self, 
                                      amount_range: tuple = (100_000, 5_000_000),
                                      network: str = "normal") -> Scenario:
        """무한 민트 공격 시나리오 생성 (100K~5M 토큰)"""
        amount = random.randint(*amount_range)
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.INFINITE_MINT,
            name="대량 민트 공격",
            description=f"{amount:,} 토큰 불법 발행 시도",
            parameters={
                'amount': amount,
                'method': 'direct_mint',
                'blocks': 1,
            },
            network_condition=network,
            expected_detection=True
        )

    def generate_catastrophic_mint_attack(self,
                                          network: str = "normal") -> Scenario:
        """
        치명적 대량 발행 공격 — 5M~50M 토큰 (Catastrophic 범위).
        이 규모의 공격은 토큰 가치를 즉시 붕괴시켜
        2계층에서도 Micro 채널로 위조 토큰이 유입되는 2차 피해가 발생합니다.
        """
        amount = random.randint(5_000_000, 50_000_000)
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.INFINITE_MINT,
            name="치명적 대량 발행 공격 (Catastrophic)",
            description=f"{amount:,} 토큰 불법 발행 — 즉각적 서비스 중단 필요",
            parameters={
                'amount': amount,
                'method': 'direct_mint',
                'blocks': 1,
                'is_catastrophic': True,
            },
            network_condition=network,
            expected_detection=True
        )
    
    def generate_burst_attacks(self, network: str = "normal") -> List[Scenario]:
        """
        큰 취약점 발생 시 대규모 연쇄 공격(Burst) 패턴 생성 — 3~8연속 공격.
        """
        burst_size = random.randint(3, 8)
        burst_scenarios = []
        for i in range(burst_size):
            amount = random.randint(3_000_000, 15_000_000)
            burst_scenarios.append(Scenario(
                label=ScenarioLabel.ATTACK,
                scenario_type=ScenarioType.RESERVE_DRAIN,
                name=f"취약점 연쇄 공격 (Burst {i+1}/{burst_size})",
                description=f"동일 취약점 반복 악용, {amount:,} 탈취 (Burst)",
                parameters={
                    'amount': amount,
                    'method': 'vault_exploit',
                    'target': 'vault',
                    'is_burst': True,
                    'burst_index': i,
                },
                network_condition=network,
                expected_detection=True
            ))
        return burst_scenarios
    
    def generate_reserve_drain_attack(self,
                                      amount_range: tuple = (10, 5000),
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
                'target': 'vault',
            },
            network_condition=network,
            expected_detection=True
        )
    
    def generate_flash_loan_attack(self,
                                   loan_range: tuple = (100_000, 100_000_000),
                                   network: str = "normal") -> Scenario:
        """플래시론 디페깅 공격 시나리오 생성"""
        loan_amount = random.randint(*loan_range)
        depeg_percent = min(35, 8 + (loan_amount / 10_000_000) * 3)
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.FLASH_LOAN_DEPEG,
            name="플래시론 가격 조작",
            description=f"${loan_amount:,} USDC 플래시론으로 {depeg_percent:.1f}% 디페그 유도",
            parameters={
                'loan_amount': loan_amount,
                'expected_depeg': depeg_percent,
                'method': 'dex_manipulation',
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
                'evasion_ratio': evasion_ratio,
            },
            network_condition=network,
            expected_detection=True
        )
    
    def generate_sybil_attack(self,
                              wallet_count: int = 10,
                              amount_per_wallet: int = 5000,
                              network: str = "normal") -> Scenario:
        """분산 공격 (Sybil Attack) 시나리오 생성 — 일반 규모"""
        total_amount = wallet_count * amount_per_wallet
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.SYBIL_ATTACK,
            name="분산 공격 (Sybil)",
            description=f"{wallet_count}개 지갑이 각각 {amount_per_wallet:,} 토큰 발행, 총 {total_amount:,}",
            parameters={
                'wallet_count': wallet_count,
                'amount_per_wallet': amount_per_wallet,
                'total_amount': total_amount,
            },
            network_condition=network,
            expected_detection=True
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
                'total_amount': total,
            },
            network_condition=network,
            expected_detection=True
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
                'total_amount': total,
            },
            network_condition=network,
            expected_detection=False
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
                'method': 'transfer',
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
                'is_verified': True,
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
                'is_whitelisted': True,
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
                'method': 'batch_transfer',
            },
            network_condition=network,
            expected_detection=False
        )
    
    def generate_micro_sybil_swarm(self, network: str = "normal") -> Scenario:
        """
        소규모 Micro 시빌 떼 공격 — 단일계층 엔진 과부하 트리거용
        """
        wallet_count = random.randint(50, 200)
        amount_per_wallet = random.randint(100, 999)
        total_amount = wallet_count * amount_per_wallet
        return Scenario(
            label=ScenarioLabel.ATTACK,
            scenario_type=ScenarioType.SYBIL_ATTACK,
            name="소규모 시빌 떼 공격 (Micro Swarm)",
            description=(
                f"{wallet_count}개 지갑 × {amount_per_wallet:,}토큰 "
                f"(임계값 미달 소액 분산) → 총 {total_amount:,}토큰"
            ),
            parameters={
                'num_wallets': wallet_count,
                'amount_per_wallet': amount_per_wallet,
                'amount': total_amount,
                'is_micro_swarm': True,
                'below_threshold': True,
            },
            network_condition=network,
            expected_detection=True
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
                'collateral_verified': True,
            },
            network_condition=network,
            expected_detection=False
        )
    
    def generate_normal_flash_loan(self,
                                   loan_range: tuple = (100_000, 100_000_000),
                                   network: str = "normal") -> Scenario:
        """정상 플래시론 (차익거래/재정거래용) 시나리오 생성"""
        loan_amount = random.randint(*loan_range)
        return Scenario(
            label=ScenarioLabel.NORMAL,
            # NORMAL_FLASH_LOAN 타입 사용 — FLASH_LOAN_DEPEG(공격)과 명확히 분리
            # feature_extractor에서 tx_frequency 배율이 4.0(공격) 대신 1.5(정상)로 적용됨
            scenario_type=ScenarioType.NORMAL_FLASH_LOAN,
            name="정상 플래시론 차익거래",
            description=f"${loan_amount:,} USDC 플래시론 반환 (합법 차익거래)",
            parameters={
                'loan_amount': loan_amount,
                'method': 'flash_loan',
                'is_whitelisted': True,  # 차익거래 컨트랙트 사전 승인(화이트리스트)
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

        공격 유형 비율 (무한발행 : 준비금탈취 : 플래시론 : 시빌 : 임계값회피 = 1:1:3:3:2)
        - 무한발행 (INFINITE_MINT):     10% — 일반 + Catastrophic 합산
        - 준비금 탈취 (RESERVE_DRAIN):  10% — 일반 + Burst 합산
        - 플래시론 (FLASH_LOAN_DEPEG):  30%
        - 시빌 공격 (SYBIL_ATTACK):     30% — 일반 + Micro Swarm 합산
        - 임계값 회피 (THRESHOLD_EVA):  20%

        Args:
            count: 생성할 시나리오 수
            network_mix: True면 다양한 네트워크 상태 혼합
        """
        scenarios = []
        networks = ['normal'] if not network_mix else ['normal', 'congested', 'severe']

        # 비율 정의: (가중치, [생성함수 리스트]) — 같은 유형 내 세부 변형은 균등 선택
        ATTACK_DISTRIBUTION = [
            # 무한발행 10% — 일반(6%) + Catastrophic(4%)
            (6,  [self.generate_infinite_mint_attack]),
            (4,  [self.generate_catastrophic_mint_attack]),
            # 준비금 탈취 10% — 일반(10%)  ※ Burst는 get_mixed_dataset에서 별도 삽입
            (10, [self.generate_reserve_drain_attack]),
            # 플래시론 30%
            (30, [self.generate_flash_loan_attack]),
            # 시빌 공격 30% — 일반(15%) + Micro Swarm(15%)
            (15, [self.generate_sybil_attack]),
            (15, [self.generate_micro_sybil_swarm]),
            # 임계값 회피 20%
            (20, [self.generate_threshold_evasion_attack]),
        ]

        # 가중치 기반 생성 목록 구성
        weighted_generators = []
        for weight, gens in ATTACK_DISTRIBUTION:
            weighted_generators.extend(gens * weight)

        for _ in range(count):
            generator = random.choice(weighted_generators)
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
            (self.generate_normal_flash_loan, 1),  # 정상 플래시론 추가
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
        
        # State Mock 주입 (Engine3 검사용)
        for s in dataset:
            self._inject_state_mock(s)

        if shuffle:
            random.shuffle(dataset)

        # 연쇄 공격(Burst)은 셔플 이후에 묶음으로 파고들어야 시간상 연속성이 유지됩니다.
        burst_count = max(1, int(total_count * 0.05 / 5))  # 총 트랜잭션의 약 5%를 Burst에 할당
        for _ in range(burst_count):
            net = random.choice(['normal', 'congested', 'severe']) if network_mix else 'normal'
            burst = self.generate_burst_attacks(network=net)
            insert_idx = random.randint(0, len(dataset))
            dataset[insert_idx:insert_idx] = burst
        
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
        
        # State Mock 주입 (Engine3 검사용)
        for s in scenarios:
            self._inject_state_mock(s)

        random.shuffle(scenarios)
        return scenarios

    # =========================================================================
    # 실제 컨트랙트 기반 데이터셋 (sample_data)
    # =========================================================================

    @staticmethod
    def _find_sample_data_root() -> Optional[str]:
        """sample_data/sample_data 디렉토리를 자동으로 탐색합니다."""
        # watchtower/lib/benchmark/ → 프로젝트 루트
        base = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )))
        candidate = os.path.join(base, "sample_data", "sample_data")
        if os.path.isdir(candidate):
            return candidate
        return None

    def get_real_contract_dataset(self,
                                  shuffle: bool = True) -> List[Scenario]:
        """
        sample_data의 실제 스마트 컨트랙트를 정적 분석하여
        레이블이 포함된 객관적 데이터셋을 반환합니다.

        Returns:
            List[Scenario] — positive(ATTACK) + negative(NORMAL)
        """
        sample_root = self._find_sample_data_root()
        if sample_root is None:
            print("[BenchmarkDataGenerator] sample_data 디렉토리를 찾을 수 없습니다.")
            return []

        # 캐시된 JSON이 있으면 빠르게 로드
        cache_path = os.path.join(os.path.dirname(sample_root), "real_contract_dataset.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            scenarios = [Scenario.from_dict(d) for d in data]
        else:
            # 직접 분석
            try:
                from .contract_analyzer import ContractAnalyzer
            except ImportError:
                from contract_analyzer import ContractAnalyzer
            analyzer = ContractAnalyzer(sample_root)
            scenarios = analyzer.generate_dataset()
            # 캐시 저장
            analyzer.export_dataset_json(cache_path)

        if shuffle:
            random.shuffle(scenarios)
        return scenarios

    def get_hybrid_dataset(self,
                           total_simulated: int = 500,
                           attack_ratio: float = 0.3,
                           network_mix: bool = True,
                           shuffle: bool = True) -> List[Scenario]:
        """
        시뮬레이션 데이터 + 실제 컨트랙트 데이터를 결합한 하이브리드 데이터셋.

        연구 논문에서 가장 객관적인 평가를 위해 사용합니다:
        - 시뮬레이션 데이터: 다양한 공격 전략과 네트워크 조건
        - 실제 컨트랙트: Ground Truth가 보장된 실제 사례

        Args:
            total_simulated: 시뮬레이션 시나리오 수
            attack_ratio: 시뮬레이션 공격 비율
            network_mix: 네트워크 상태 다양화
            shuffle: 셔플 여부
        """
        simulated = self.get_mixed_dataset(
            total_count=total_simulated,
            attack_ratio=attack_ratio,
            network_mix=network_mix,
            shuffle=False,
        )
        real = self.get_real_contract_dataset(shuffle=False)

        dataset = simulated + real

        if shuffle:
            random.shuffle(dataset)
        return dataset

    def get_0728_real_transaction_dataset(self, limit: int = 1000, shuffle: bool = True) -> List[Scenario]:
        """
        sample_data/archive/07-28의 실제 트랜잭션 데이터를 읽어 반환합니다.
        
        Args:
            limit: 최대 로드 파일 수 제한
            shuffle: 셔플 여부
        """
        import glob
        
        base = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )))
        archive_path = os.path.join(base, "sample_data", "archive", "07-28")
        
        if not os.path.isdir(archive_path):
            print(f"[BenchmarkDataGenerator] {archive_path} 경로를 찾을 수 없습니다.")
            return []
            
        json_files = glob.glob(os.path.join(archive_path, "*.json"))
        if shuffle:
            random.shuffle(json_files)
            
        if limit > 0:
            json_files = json_files[:limit]
            
        scenarios = []
        for file_path in json_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    
                # 샌드위치 공격 판별
                is_sandwich_attacker = False
                summary = data.get('summary', {})
                types_list = summary.get('types', [])
                
                if any(t in ['Sandwich', 'PartialSandwich'] for t in types_list):
                    is_sandwich_attacker = True
                
                token_flows = data.get('tokenFlows', [])
                if not is_sandwich_attacker:
                    for flow in token_flows:
                        if 'SandwichAttacker' in flow.get('tags', []):
                            is_sandwich_attacker = True
                            break
                            
                profit_str = summary.get('profit', 0)
                try:
                    profit = float(profit_str)
                except (ValueError, TypeError):
                    profit = 0.0
                profit_wei = int(profit * 1e18) 
                
                amount = profit if profit > 0 else 500000.0  # 정규화된 금액 사용
                
                scenario_type = ScenarioType.SANDWICH_ATTACK if is_sandwich_attacker else ScenarioType.NORMAL_FLASH_LOAN
                label = ScenarioLabel.ATTACK if is_sandwich_attacker else ScenarioLabel.NORMAL
                
                scenario = Scenario(
                    id=os.path.basename(file_path)[:8],
                    label=label,
                    scenario_type=scenario_type,
                    name=f"실제 TX ({scenario_type.value})",
                    description=f"07-28 실제 TX 분석 데이터",
                    parameters={
                        'amount': amount,
                        'profit_wei': profit_wei,
                        'method': 'real_tx',
                        'is_whitelisted': not is_sandwich_attacker,
                    },
                    network_condition='normal',
                    expected_detection=is_sandwich_attacker
                )
                
                # Mock 주입
                self._inject_state_mock(scenario)
                scenarios.append(scenario)
                
            except Exception as e:
                continue
                
        return scenarios

