import { ethers } from "hardhat";

async function main() {
  console.log("🚀 FDS Stablecoin 배포 및 설정 시작...\n");

  const [deployer, watchtower] = await ethers.getSigners();
  console.log(`👨‍💻 배포자(Owner): ${deployer.address}`);
  console.log(`👀 감시자(Watchtower): ${watchtower.address}`);

  // 1. 배포
  const FDSStablecoin = await ethers.getContractFactory("FDSStablecoin");
  const fdsToken = await FDSStablecoin.deploy();
  await fdsToken.waitForDeployment();
  const tokenAddress = await fdsToken.getAddress();

  console.log(`✅ 배포 완료! 주소: ${tokenAddress}`);

  // 2. [핵심] Watchtower 등록
  console.log("⚙️ Watchtower 등록 중...");
  const tx = await fdsToken.setWatchtower(watchtower.address);
  await tx.wait();
  
  console.log("✅ Watchtower 등록 완료!");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
