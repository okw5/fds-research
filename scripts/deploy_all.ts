import { ethers } from "hardhat";
import fs from "fs";
import path from "path";

async function main() {
  console.log("🚀 FDS 종합 연구 환경 구축 시작 (단일 토큰 + 2계층 모델)...\n");
  const [deployer, watchtower] = await ethers.getSigners();

  console.log(`📋 배포자: ${deployer.address}`);
  console.log(`👁️ Watchtower: ${watchtower.address}\n`);

  // ========================================
  // Part 1: Control Group - 단일 토큰 모델 (Model A)
  // ========================================
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("📊 [Model A] 단일 토큰 모델 배포 시작");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");

  // 1. FDS Stablecoin 배포 (Control Group)
  console.log("🪙 [Model A] FDS Stablecoin (Single Layer) 배포 중...");
  const FDS = await ethers.getContractFactory("FDSStablecoin");
  const fds = await FDS.deploy();
  await fds.waitForDeployment();
  const fdsAddr = await fds.getAddress();
  console.log(`   ✓ FDS Stablecoin 배포 완료: ${fdsAddr}`);

  // Watchtower 등록
  await fds.setWatchtower(watchtower.address);
  console.log(`   ✓ Watchtower 설정 완료\n`);

  // ========================================
  // Part 2: Experimental Group - 2계층 토큰 모델 (Model B)
  // ========================================
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("🛡️  [Model B] 2계층 토큰 모델 배포 시작");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");

  // 2-1. Micro Token (소액 결제용)
  console.log("💳 [Model B] FDS Micro Token 배포 중...");
  const Micro = await ethers.getContractFactory("FDSMicroToken");
  const micro = await Micro.deploy();
  await micro.waitForDeployment();
  const microAddr = await micro.getAddress();
  console.log(`   ✓ FDS Micro Token 배포 완료: ${microAddr}`);
  console.log(`   📌 특징: 100만원 이하 소액 결제, 사전 심사 불필요\n`);

  // 2-2. Macro Token (거액 결제용)
  console.log("🏦 [Model B] FDS Macro Token 배포 중...");
  const Macro = await ethers.getContractFactory("FDSMacroToken");
  const macro = await Macro.deploy();
  await macro.waitForDeployment();
  const macroAddr = await macro.getAddress();
  console.log(`   ✓ FDS Macro Token 배포 완료: ${macroAddr}`);
  console.log(`   📌 특징: 100만원 초과 거액 결제, 사전 심사 필수, 서킷 브레이커 적용`);

  // Macro Token Watchtower 설정
  await macro.setWatchtower(watchtower.address);
  console.log(`   ✓ Watchtower 설정 완료\n`);

  // ========================================
  // Part 3: Mock Infrastructure (공통 사용)
  // ========================================
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("🏗️  Mock Infrastructure 배포 시작");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");

  // 3. Mock USDT 배포
  console.log("💵 Mock USDT 배포 중...");
  const USDT = await ethers.getContractFactory("MockUSDT");
  const usdt = await USDT.deploy();
  await usdt.waitForDeployment();
  const usdtAddr = await usdt.getAddress();
  console.log(`   ✓ Mock USDT 배포 완료: ${usdtAddr}\n`);

  // 4. Mock Vault 배포 & 자금 충전
  console.log("🏦 Mock Vault 배포 및 충전 중...");
  const Vault = await ethers.getContractFactory("MockVault");
  const vault = await Vault.deploy(usdtAddr);
  await vault.waitForDeployment();
  const vaultAddr = await vault.getAddress();
  console.log(`   ✓ Mock Vault 배포 완료: ${vaultAddr}`);

  // Vault에 100만 달러 충전
  await usdt.transfer(vaultAddr, ethers.parseEther("1000000"));
  console.log(`   ✓ Vault에 1,000,000 USDT 충전 완료\n`);

  // 5. Mock Oracle 배포
  console.log("🔮 Mock Oracle 배포 중...");
  const Oracle = await ethers.getContractFactory("MockOracle");
  const oracle = await Oracle.deploy();
  await oracle.waitForDeployment();
  const oracleAddr = await oracle.getAddress();
  console.log(`   ✓ Mock Oracle 배포 완료: ${oracleAddr}\n`);

  // 6. Mock DEX 배포 & 유동성 공급
  console.log("⚖️  Mock DEX 배포 및 유동성 공급 중...");
  const DEX = await ethers.getContractFactory("MockDEX");
  const dex = await DEX.deploy(fdsAddr, usdtAddr);
  await dex.waitForDeployment();
  const dexAddr = await dex.getAddress();
  console.log(`   ✓ Mock DEX 배포 완료: ${dexAddr}`);

  // DEX에 유동성 공급 (FDS 50만개 + USDT 50만개 = $1.00 가격 형성)
  await fds.approve(dexAddr, ethers.parseEther("1000000"));
  await usdt.approve(dexAddr, ethers.parseEther("1000000"));

  await dex.addLiquidity(
    ethers.parseEther("500000"), // 500k FDS
    ethers.parseEther("500000")  // 500k USDT
  );
  console.log(`   ✓ DEX 유동성 공급 완료: 500,000 FDS + 500,000 USDT\n`);

  // ========================================
  // Part 4: 주소 및 ABI 저장
  // ========================================
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("💾 주소 및 ABI 파일 저장 중");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");

  // 주소 저장
  const addresses = {
    // Model A: 단일 토큰
    FDS: fdsAddr,

    // Model B: 2계층 토큰
    FDSMicro: microAddr,
    FDSMacro: macroAddr,

    // Mock Infrastructure
    USDT: usdtAddr,
    Vault: vaultAddr,
    Oracle: oracleAddr,
    DEX: dexAddr
  };

  const watchtowerDir = path.join(__dirname, "../watchtower");
  if (!fs.existsSync(watchtowerDir)) fs.mkdirSync(watchtowerDir);

  const addressPath = path.join(watchtowerDir, "addresses.json");
  fs.writeFileSync(addressPath, JSON.stringify(addresses, null, 2));
  console.log(`   ✓ 주소 파일 저장: ${addressPath}\n`);

  // ABI 파일 복사 (UI용)
  const copyArtifact = (contractName: string, fileName?: string) => {
    const src = path.join(__dirname, `../artifacts/contracts/${contractName}.sol/${contractName}.json`);

    if (fs.existsSync(src)) {
      const dest = path.join(watchtowerDir, fileName || `${contractName}.json`);
      fs.copyFileSync(src, dest);
      console.log(`   ✓ ABI 복사: ${contractName}`);
    } else {
      console.warn(`   ⚠️  Artifact not found: ${contractName}`);
    }
  };

  // 토큰 컨트랙트 ABI 복사
  copyArtifact("FDSStablecoin");
  copyArtifact("FDSMicroToken");
  copyArtifact("FDSMacroToken");

  // Mock Infrastructure ABI 복사
  const copyMock = (solFile: string, contract: string) => {
    const src = path.join(__dirname, `../artifacts/contracts/${solFile}/${contract}.json`);
    if (fs.existsSync(src)) {
      fs.copyFileSync(src, path.join(watchtowerDir, `${contract}.json`));
      console.log(`   ✓ ABI 복사: ${contract}`);
    }
  }

  copyMock("MockInfrastructure.sol", "MockDEX");
  copyMock("MockInfrastructure.sol", "MockVault");
  copyMock("MockInfrastructure.sol", "MockUSDT");
  copyMock("MockInfrastructure.sol", "MockOracle");

  // ========================================
  // Part 5: 배포 완료 요약
  // ========================================
  console.log("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
  console.log("✅ 모든 배포 및 설정 완료!");
  console.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");

  console.log("📊 배포된 컨트랙트 주소:\n");
  console.table(addresses);

  console.log("\n📝 실험 가능한 모델:");
  console.log("   [Model A] 단일 토큰: FDSStablecoin");
  console.log("   [Model B] 2계층 토큰: FDSMicroToken + FDSMacroToken");
  console.log("\n🎯 다음 단계:");
  console.log("   1. Watchtower 서버 실행");
  console.log("   2. Experiment Runner에서 시나리오 선택");
  console.log("   3. 실험설계_및_예상결과.md 참고하여 각 공격 시나리오 실행\n");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
