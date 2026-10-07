// OAuth clients and tokens for the official posting APIs, encrypted with Electron safeStorage (the key lives in the
// OS keychain, like the AI API keys in secrets.ts). Only ciphertext is written, to <userData>/publish-api.json;
// nothing here ever goes to the renderer, a log or the engine. No keychain (Linux without a keyring) = refused.
import fs from 'node:fs';
import path from 'node:path';
import type { Crypto } from '../../secrets';

export interface ApiSecret {
  clientId?: string;
  clientSecret?: string;
  refreshToken?: string;
  scope?: string;
  connectedAt?: string;
}

export class ApiVault {
  private file: string;

  constructor(
    dir: string,
    private crypto: Crypto,
    private platform: NodeJS.Platform = process.platform,
  ) {
    this.file = path.join(dir, 'publish-api.json');
  }

  keychain(): boolean {
    if (!this.crypto.isEncryptionAvailable()) return false;
    return !(this.platform === 'linux' && this.crypto.getSelectedStorageBackend?.() === 'basic_text');
  }

  private readAll(): Record<string, string> {
    try {
      const raw = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      return raw && typeof raw === 'object' ? raw : {};
    } catch {
      return {};
    }
  }

  get(id: string): ApiSecret {
    const v = this.readAll()[id];
    if (!v || !this.crypto.isEncryptionAvailable()) return {};
    try {
      return JSON.parse(this.crypto.decryptString(Buffer.from(v, 'base64'))) as ApiSecret;
    } catch {
      return {}; // written under a keychain item this app can no longer read: ask again
    }
  }

  set(id: string, patch: ApiSecret | null) {
    if (patch && !this.keychain()) throw new Error('the OS keychain is not available: nothing is stored');
    const all = this.readAll();
    if (patch === null) delete all[id];
    else all[id] = this.crypto.encryptString(JSON.stringify({ ...this.get(id), ...patch })).toString('base64');
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const tmp = this.file + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(all), { mode: 0o600 });
    fs.renameSync(tmp, this.file);
  }
}
