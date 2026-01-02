import { ethers } from "hardhat";

async function main() {
  console.log("🛡️  서킷 브레이커 수동 테스트 시작...\n");

  // 1. 등장인물 준비 (나: Owner, 해커: User)
  const [owner, hacker] = await ethers.getSigners();
  
  // 2. 테스트를 위해 토큰을 새로 배포합니다.
  const FDSStablecoin = await ethers.getContractFactory("FDSStablecoin");
  const token = await FDSStablecoin.deploy();
  await token.waitForDeployment();
  console.log(`✅ 토큰 배포 완료: ${await token.getAddress()}`);

  // ---------------------------------------------------------
  // 시나리오 1: 평화로운 상태에서의 전송 (성공해야 함)
  // ---------------------------------------------------------
  console.log("\n[Step 1] 🕊️ 평화로운 상태: 전송 시도");
  try {
    await token.transfer(hacker.address, ethers.parseEther("100"));
    console.log("👉 전송 성공! (정상)");
  } catch (error) {
    console.log("❌ 전송 실패 (비정상)");
  }

  // ---------------------------------------------------------
  // 시나리오 2: 서킷 브레이커 발동 (Pause)
  // ---------------------------------------------------------
  console.log("\n[Step 2] 🚨 이상 징후 발견! 서킷 브레이커 발동!");
  const tx = await token.circuitBreakerTrigger();
  await tx.wait();
  console.log("👉 시스템 동결 완료 (Paused)");

  // ---------------------------------------------------------
  // 시나리오 3: 동결 상태에서의 전송 (실패해야 함)
  // ---------------------------------------------------------
  console.log("\n[Step 3] 🏴‍☠️ 해킹 시도: 자금 탈취 시도");
  try {
    await token.transfer(hacker.address, ethers.parseEther("500"));
    console.log("❌ 막지 못함! 전송되어버림 (테스트 실패)");
  } catch (error: any) {
    // 에러 메시지에 'EnforcedPause'가 포함되어 있으면 성공
    if (error.message.includes("EnforcedPause")) {
        console.log("✅ 방어 성공! 'EnforcedPause' 에러 발생하며 전송 차단됨.");
    } else {
        console.log("✅ 방어 성공! (전송 실패함)");
    }
  }

  // ---------------------------------------------------------
  // 시나리오 4: 서비스 재개 (Unpause)
  // ---------------------------------------------------------
  console.log("\n[Step 4] 🟢 상황 종료: 서비스 재개");
  const resumeTx = await token.resumeService();
  await resumeTx.wait();
  console.log("👉 시스템 정상화 완료");

  // ---------------------------------------------------------
  // 시나리오 5: 재개 후 전송 (성공해야 함)
  // ---------------------------------------------------------
  console.log("\n[Step 5] 🕊️ 서비스 재개 후 전송 시도");
  try {
    await token.transfer(hacker.address, ethers.parseEther("50"));
    console.log("👉 전송 성공! (정상 복구됨)");
  } catch (error) {
    console.log("❌ 전송 실패 (복구 안됨)");
  }

  // 최종 잔액 확인
  const hackerBalance = await token.balanceOf(hacker.address);
  console.log(`\n💰 해커가 최종적으로 가져간 돈: ${ethers.formatEther(hackerBalance)} FDS (100+50=150 이어야 함)`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
