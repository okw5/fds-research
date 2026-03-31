import { HardhatUserConfig } from "hardhat/config";
import "@nomicfoundation/hardhat-ethers"; // <--- 이렇게 변경!
import "dotenv/config";

const MAINNET_RPC_URL = process.env.MAINNET_RPC_URL || "";

const config: HardhatUserConfig = {
  solidity: {
    compilers: [
      { version: "0.8.27", settings: { optimizer: { enabled: true, runs: 200 } } },
      { version: "0.8.24", settings: { optimizer: { enabled: true, runs: 200 } } },
      { version: "0.8.20", settings: { optimizer: { enabled: true, runs: 200 } } },
      { version: "0.8.19", settings: { optimizer: { enabled: true, runs: 200 } } },
      { version: "0.8.10", settings: { optimizer: { enabled: true, runs: 200 } } },
      { version: "0.8.4", settings: { optimizer: { enabled: true, runs: 200 } } },
      { version: "0.8.0", settings: { optimizer: { enabled: true, runs: 200 } } },
      { version: "0.6.12", settings: { optimizer: { enabled: true, runs: 200 } } },
      { version: "0.5.17", settings: { optimizer: { enabled: true, runs: 200 } } }
    ]
  },
  networks: {
    hardhat: {
      forking: {
        url: MAINNET_RPC_URL,
        enabled: true,
      },
      mining: {
        auto: true,
      },
      chainId: 31337,
    },
  },
};

export default config;
