# fds-research

간단한 설명
- 이 저장소는 Hardhat + TypeScript 기반의 스마트컨트랙트(연구/실험) 프로젝트입니다.
- contracts, scripts, test, ignition 등의 디렉터리를 포함하고 있어 로컬 개발, 컴파일, 테스트, 배포 흐름을 제공하도록 구성되어 있습니다.

목표 (설명할 내용 예시)
- 연구 목적의 스마트컨트랙트 개발 / 실험
- 예: 가스 최적화, 프로토콜 설계 실험, 인터페이스 테스트 등
(프로젝트의 구체 목적을 원하시면 contracts 디렉터리 아래 각 컨트랙트 설명을 알려주세요. README의 이 부분을 구체화해 드리겠습니다.)

저장소 구조
- contracts/        : Solidity 컨트랙트 소스 (현재 디렉터리 존재)
- ignition/         : 배포/시나리오 정의(하드햇 Ignition 매니페스트 등)
- scripts/          : 배포 또는 헬퍼 스크립트
- test/             : 테스트(하드햇/무타치 등)
- hardhat.config.ts : Hardhat 구성(타입스크립트)
- package.json      : 의존성 및 NPM 스크립트
- tsconfig.json     : TypeScript 설정
- .env.example      : 필요한 환경변수 예시

요구사항
- Node.js (v16 이상 권장)
- npm 또는 yarn
- (선택) Alchemy/Infura API 키, Etherscan API 키, 배포용 지갑 프라이빗 키 등

설정 및 시작 (예시)
1. 저장소 클론
   git clone https://github.com/okw5/fds-research.git
   cd fds-research

2. 의존성 설치
   npm install
   또는
   yarn install

3. 환경변수 설정
   .env.example 파일을 복사하여 .env로 만들고 필요한 값을 채우세요.
   예시 키 (프로젝트에 맞게 .env.example을 확인하고 동일하게 채우세요):
   - RPC_URL (예: Alchemy/Infura 엔드포인트)
   - PRIVATE_KEY (배포용 지갑)
   - ETHERSCAN_API_KEY (컨트랙트 검증 시)

4. 컴파일
   npx hardhat compile

5. 테스트
   npx hardhat test

6. 로컬 노드 실행 (옵션)
   npx hardhat node

7. 배포 (예시)
   테스트 블록체인 시작 npx hardhat node --fork https://eth-mainnet.g.alchemy.com/v2/본인키
   컨트렉트 배포 npx hardhat run scripts/deploy_all.ts --network localhost
   웹 UI서비스 시작 ./watchtower/streamlit run app.py

   


