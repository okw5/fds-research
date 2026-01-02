import { ethers } from "hardhat";

async function main() {
  console.log("🚀 FDS Stablecoin 배포 시작...\n");

  // 1. 배포자(Owner) 계정 가져오기
  // Hardhat이 제공하는 첫 번째 테스트 계정을 사용합니다.
  const [deployer] = await ethers.getSigners();
  console.log(`👨‍💻 배포자 주소(Owner): ${deployer.address}`);

  // 배포 전 잔액 확인 (선택 사항)
  const balance = await ethers.provider.getBalance(deployer.address);
  console.log(`💰 배포자 잔액: ${ethers.formatEther(balance)} ETH\n`);

  // 2. 스마트 컨트랙트 공장(Factory) 가져오기
  // "FDSStablecoin"은 우리가 작성한 솔리디티 파일의 contract 이름과 같아야 합니다.
  const FDSStablecoin = await ethers.getContractFactory("FDSStablecoin");

  // 3. 배포 트랜잭션 전송
  // 생성자(constructor)에 인자가 있다면 deploy() 안에 넣어줍니다. (우린 없음)
  const fdsToken = await FDSStablecoin.deploy();

  // 4. 배포 완료 대기
  await fdsToken.waitForDeployment();

  // 5. 결과 출력
  const tokenAddress = await fdsToken.getAddress();
  console.log(`✅ FDS Stablecoin 배포 완료!`);
  console.log(`📍 토큰 주소: ${tokenAddress}`);
}

// 에러 처리 패턴
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
