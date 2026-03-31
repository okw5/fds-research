import * as fs from 'fs';
import * as path from 'path';

function getSolidityVersion(content: string): string | null {
    const match = content.match(/pragma solidity\s+([^;]+);/);
    if (match) {
        return match[1].trim();
    }
    return null;
}

function scanDir(dir: string, versions: Set<string>) {
    const files = fs.readdirSync(dir);
    for (const file of files) {
        const fullPath = path.join(dir, file);
        if (fs.statSync(fullPath).isDirectory()) {
            scanDir(fullPath, versions);
        } else if (fullPath.endsWith('.sol')) {
            const content = fs.readFileSync(fullPath, 'utf8');
            const v = getSolidityVersion(content);
            if (v) {
                versions.add(v);
            }
        }
    }
}

const dir = path.join(__dirname, '../sample_data/sample_data');
const versions = new Set<string>();
scanDir(dir, versions);
console.log('Detected Solidity versions:');
console.log(Array.from(versions));
