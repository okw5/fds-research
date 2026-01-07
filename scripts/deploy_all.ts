import { ethers } from "hardhat";
import fs from "fs";
import path from "path";

async function main() {
  console.log("🚀 FDS 종합 연구 환경 구축 시작...\n");
  const [deployer, watchtower] = await ethers.getSigners();

  // 1. FDS Stablecoin 배포
  console.log("🪙 FDS Stablecoin 배포 중...");
  const FDS = await ethers.getContractFactory("FDSStablecoin");
  const fds = await FDS.deploy();
  await fds.waitForDeployment();
  const fdsAddr = await fds.getAddress();
  
  // Watchtower 등록
  await fds.setWatchtower(watchtower.address);

  // 2. Mock USDT 배포
  console.log("💵 Mock USDT 배포 중...");
  const USDT = await ethers.getContractFactory("MockUSDT");
  const usdt = await USDT.deploy();
  await usdt.waitForDeployment();
  const usdtAddr = await usdt.getAddress();

  // 3. Mock Vault 배포 & 자금 충전
  console.log("🏦 Mock Vault 배포 및 충전 중...");
  const Vault = await ethers.getContractFactory("MockVault");
  const vault = await Vault.deploy(usdtAddr);
  await vault.waitForDeployment();
  const vaultAddr = await vault.getAddress();

  // Vault에 100만 달러 넣기
  await usdt.transfer(vaultAddr, ethers.parseEther("1000000"));

  // 4. Mock Oracle 배포
  console.log("🔮 Mock Oracle 배포 중...");
  const Oracle = await ethers.getContractFactory("MockOracle");
  const oracle = await Oracle.deploy();
  await oracle.waitForDeployment();
  const oracleAddr = await oracle.getAddress();

  // 5. Mock DEX 배포 & 유동성 공급
  console.log("⚖️ Mock DEX 배포 및 유동성 공급 중...");
  const DEX = await ethers.getContractFactory("MockDEX");
  const dex = await DEX.deploy(fdsAddr, usdtAddr);
  await dex.waitForDeployment();
  const dexAddr = await dex.getAddress();

  // DEX에 유동성 공급 (FDS 50만개 + USDT 50만개 = $1.00 가격 형성)
  // 먼저 DEX가 돈을 가져갈 수 있게 approve
  await fds.approve(dexAddr, ethers.parseEther("1000000"));
  await usdt.approve(dexAddr, ethers.parseEther("1000000"));
  
  await dex.addLiquidity(
      ethers.parseEther("500000"), // 500k FDS
      ethers.parseEther("500000")  // 500k USDT
  );

  // 6. 주소 저장
  const addresses = {
    FDS: fdsAddr,
    USDT: usdtAddr,
    Vault: vaultAddr,
    Oracle: oracleAddr,
    DEX: dexAddr
  };

  const watchtowerDir = path.join(__dirname, "../watchtower");
  if (!fs.existsSync(watchtowerDir)) fs.mkdirSync(watchtowerDir);

  const addressPath = path.join(watchtowerDir, "addresses.json");
  fs.writeFileSync(addressPath, JSON.stringify(addresses, null, 2));

  // 7. ABI 파일 복사 (UI용) 
  // (Hardhat artifacts -> watchtower/)
  const copyArtifact = (contractName: string, fileName?: string) => {
    const src = path.join(__dirname, `../artifacts/contracts/${contractName}.sol/${contractName}.json`);
    // Mock 컨트랙트는 contracts 폴더 바로 밑에 있는지, 아니면 별도 파일에 있는지 확인 필요.
    // 여기서는 간단히 FDSStablecoin만 확실시하고 나머지는 예외처리 하거나 경로 가정.
    // 사용자 파일 구조상 Mock... sol 파일들이 contracts/ 에 바로 있음.
    
    if (fs.existsSync(src)) {
        const dest = path.join(watchtowerDir, fileName || `${contractName}.json`);
        fs.copyFileSync(src, dest);
        console.log(`📄 Copied ABI: ${contractName}`);
    } else {
        console.warn(`⚠️ Artifact not found for: ${contractName}`);
    }
  };

  copyArtifact("FDSStablecoin");
  // Mock 시리즈는 보통 파일명이 다를 수 있으니 유의 (MockInfrastructure.sol 안에 다 있는지 등)
  // MockDEX, MockVault가 MockInfrastructure.sol 안에 있다면 artifacts 구조가 다름.
  
  // artifacts/contracts/MockInfrastructure.sol/MockDEX.json
  const copyMock = (solFile: string, contract: string) => {
      const src = path.join(__dirname, `../artifacts/contracts/${solFile}/${contract}.json`);
      if (fs.existsSync(src)) {
          fs.copyFileSync(src, path.join(watchtowerDir, `${contract}.json`));
          console.log(`📄 Copied ABI: ${contract}`);
      }
  }

  copyMock("MockInfrastructure.sol", "MockDEX");
  copyMock("MockInfrastructure.sol", "MockVault");
  copyMock("MockInfrastructure.sol", "MockUSDT"); 
  copyMock("MockInfrastructure.sol", "MockOracle");

  console.log("\n✅ 모든 배포 및 설정 완료!");
  console.table(addresses);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
