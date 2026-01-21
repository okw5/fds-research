import { ethers } from "hardhat";
import fs from "fs";
import path from "path";

async function main() {
    console.log("🚀 FDS 2-Layer 보안 모델 실험 환경 구축 시작...\n");
    const [deployer, watchtower] = await ethers.getSigners();

    // 1. [Control Group] FDS Stablecoin (기존 단일 토큰 모델) 배포
    console.log("🪙 [Model A] FDS Stablecoin (Single Layer) 배포 중...");
    const FDS = await ethers.getContractFactory("FDSStablecoin");
    const fds = await FDS.deploy();
    await fds.waitForDeployment();
    const fdsAddr = await fds.getAddress();
    await fds.setWatchtower(watchtower.address);

    // 2. [Experimental Group] 2-Layer Token Model 배포
    console.log("🛡️ [Model B] FDS Micro & Macro Tokens (2-Layer) 배포 중...");

    // 2-1. Micro Token
    const Micro = await ethers.getContractFactory("FDSMicroToken");
    const micro = await Micro.deploy();
    await micro.waitForDeployment();
    const microAddr = await micro.getAddress();

    // 2-2. Macro Token
    const Macro = await ethers.getContractFactory("FDSMacroToken");
    const macro = await Macro.deploy();
    await macro.waitForDeployment();
    const macroAddr = await macro.getAddress();

    // Macro Token 설정
    await macro.setWatchtower(watchtower.address);

    // 3. Mock Infrastructure (Optional, but kept for compatibility)
    console.log("🏗️ Mock Infrastructure 배포 중...");

    // USDT
    const USDT = await ethers.getContractFactory("MockUSDT");
    const usdt = await USDT.deploy();
    await usdt.waitForDeployment();
    const usdtAddr = await usdt.getAddress();

    // 6. 주소 저장
    const addresses = {
        FDS: fdsAddr,
        FDSMicro: microAddr,
        FDSMacro: macroAddr,
        USDT: usdtAddr,
    };

    const watchtowerDir = path.join(__dirname, "../watchtower");
    if (!fs.existsSync(watchtowerDir)) fs.mkdirSync(watchtowerDir);

    const addressPath = path.join(watchtowerDir, "addresses.json");
    fs.writeFileSync(addressPath, JSON.stringify(addresses, null, 2));

    // 7. ABI 파일 복사 (UI용)
    const copyArtifact = (contractName: string, fileName?: string) => {
        const src = path.join(__dirname, `../artifacts/contracts/${contractName}.sol/${contractName}.json`);

        if (fs.existsSync(src)) {
            const dest = path.join(watchtowerDir, fileName || `${contractName}.json`);
            fs.copyFileSync(src, dest);
            console.log(`📄 Copied ABI: ${contractName}`);
        } else {
            console.warn(`⚠️ Artifact not found for: ${contractName}`);
        }
    };

    copyArtifact("FDSStablecoin");
    copyArtifact("FDSMicroToken");
    copyArtifact("FDSMacroToken");

    // Mock Infrastructures
    const copyMock = (solFile: string, contract: string) => {
        const src = path.join(__dirname, `../artifacts/contracts/${solFile}/${contract}.json`);
        if (fs.existsSync(src)) {
            fs.copyFileSync(src, path.join(watchtowerDir, `${contract}.json`));
            console.log(`📄 Copied ABI: ${contract}`);
        }
    }
    copyMock("MockInfrastructure.sol", "MockUSDT");

    console.log("\n✅ 2-Layer 모델 실험 환경 구축 완료!");
    console.table(addresses);
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
