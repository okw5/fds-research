import { ethers } from "hardhat";

async function main() {
  console.log("🔐 서명 기반(ECDSA) 서킷 브레이커 테스트 시작...\n");

  const [deployer, watchtowerWallet, hacker] = await ethers.getSigners();
  
  // 1. 컨트랙트 배포
  const FDSStablecoin = await ethers.getContractFactory("FDSStablecoin");
  const token = await FDSStablecoin.deploy();
  await token.waitForDeployment();
  const tokenAddress = await token.getAddress();
  console.log(`✅ 토큰 배포 완료: ${tokenAddress}`);

  // 2. Watchtower 등록 (Owner가 수행)
  await token.setWatchtower(watchtowerWallet.address);
  console.log(`👀 Watchtower 주소 등록 완료: ${watchtowerWallet.address}`);

  // ---------------------------------------------------------
  // 시나리오: Watchtower가 해킹 감지 -> 서명 생성 -> 제3자가 제출
  // ---------------------------------------------------------
  
  console.log("\n[Step 1] 📝 오프체인: 서명 생성 중...");

  // 컨트랙트 내부 로직과 똑같은 데이터를 준비합니다.
  // 내용: "EMERGENCY_PAUSE", 체인ID, 컨트랙트주소, Nonce
  const network = await ethers.provider.getNetwork(); // 체인ID 가져오기
  const nonce = await token.nonces(watchtowerWallet.address); // 현재 Nonce 가져오기

  // 데이터 해시 생성 (Solidity의 abi.encodePacked와 동일)
  const messageHash = ethers.solidityPackedKeccak256(
    ["string", "uint256", "address", "uint256"],
    ["EMERGENCY_PAUSE", network.chainId, tokenAddress, nonce]
  );

  // 서명 생성 (Watchtower의 개인키로 서명)
  // ethers.getBytes는 문자열 해시를 바이트 배열로 변환해줍니다.
  const signature = await watchtowerWallet.signMessage(ethers.getBytes(messageHash));
  console.log(`👉 생성된 서명: ${signature.substring(0, 30)}...`);

  // ---------------------------------------------------------
  // 시나리오: 검증 및 차단
  // ---------------------------------------------------------
  
  console.log("\n[Step 2] 🚀 온체인: 서명 제출 및 차단 시도");

  // 주의: 서명 제출은 해커나 제3자가 해도 상관없습니다. (서명 내용이 중요하니까요)
  // 여기서는 'deployer'가 대신 제출한다고 가정합니다.
  try {
    const tx = await token.connect(deployer).pauseByWatchtower(signature);
    await tx.wait();
    console.log("✅ 서명 검증 성공! 시스템이 동결되었습니다 (Paused).");
  } catch (error) {
    console.error("❌ 서명 검증 실패!", error);
  }

  // ---------------------------------------------------------
  // 확인: 진짜 멈췄나?
  // ---------------------------------------------------------
  console.log("\n[Step 3] 🕵️ 상태 확인");
  const isPaused = await token.paused();
  if (isPaused) {
      console.log("🧊 현재 상태: PAUSED (성공)");
  } else {
      console.log("🔥 현재 상태: UNPAUSED (실패)");
  }

  // ---------------------------------------------------------
  // 재사용 공격 테스트 (Replay Attack)
  // ---------------------------------------------------------
  console.log("\n[Step 4] ♻️ 재사용 공격 시도 (같은 서명 다시 제출)");
  try {
      // 시스템을 잠깐 풉니다.
      await token.resumeService();
      
      // 아까 쓴 서명을 다시 제출해봅니다.
      await token.connect(deployer).pauseByWatchtower(signature);
      console.log("❌ 실패: 이미 쓴 서명이 받아들여짐 (심각한 보안 문제)");
  } catch (error: any) {
      if (error.message.includes("Invalid signature")) {
        console.log("✅ 방어 성공! 'Invalid signature' (Nonce가 달라서 서명 불일치)");
      } else {
        console.log("✅ 방어 성공! (다른 에러 발생)");
      }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
