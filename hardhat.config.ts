import { HardhatUserConfig } from "hardhat/config";
import "@nomicfoundation/hardhat-ethers"; // <--- 이렇게 변경!
import "dotenv/config";

const MAINNET_RPC_URL = process.env.MAINNET_RPC_URL || "";

const config: HardhatUserConfig = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200,
      },
    },
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
