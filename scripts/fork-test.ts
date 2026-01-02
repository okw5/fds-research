import { ethers, network } from "hardhat";

async function main() {
  console.log("🛠️  로컬 메인넷 포크 테스트 시작...\n");

  // 1. 테스트용 고래(Whale) 지갑 주소 (예: Binance Hot Wallet)
  const WHALE_ADDRESS = "0xF977814e90dA44bFA03b6295A0616a897441aceC";

  // 2. Impersonate Account (이 지갑을 내 것처럼 사용하겠다고 선언)
  // 서명 없이도 이 지갑의 돈을 뺄 수 있게 해주는 Hardhat의 기능입니다.
  await network.provider.request({
    method: "hardhat_impersonateAccount",
    params: [WHALE_ADDRESS],
  });

  const whaleSigner = await ethers.getSigner(WHALE_ADDRESS);

  // 3. 잔액 확인
  const balanceBefore = await ethers.provider.getBalance(WHALE_ADDRESS);
  console.log(`💰 고래 지갑 잔액: ${ethers.formatEther(balanceBefore)} ETH`);

  // 4. 가짜 트랜잭션 발생 (내 지갑으로 100 ETH 전송)
  const [myWallet] = await ethers.getSigners();
  console.log(`\n💸 100 ETH를 내 지갑(${myWallet.address})으로 전송 시도...`);

  await whaleSigner.sendTransaction({
    to: myWallet.address,
    value: ethers.parseEther("100"),
  });

  // 5. 결과 확인
  const myBalance = await ethers.provider.getBalance(myWallet.address);
  console.log(`✅ 전송 완료! 내 지갑 잔액: ${ethers.formatEther(myBalance)} ETH`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
