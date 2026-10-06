// API keys in the OS keychain, without native modules: Electron safeStorage encrypts with a key held by the
// OS keychain (macOS Keychain, Windows DPAPI, libsecret/kwallet on Linux). Only the ciphertext is written to
// <userData>/secrets.json. Plaintext keys never go back to the renderer and never hit disk or logs; the main
// process decrypts them only to put them in the engine sidecar's environment.
import fs from 'node:fs';
import path from 'node:path';

export type SecretName = 'anthropic' | 'openai';
export const SECRET_ENV: Record<SecretName, string> = { anthropic: 'ANTHROPIC_API_KEY', openai: 'OPENAI_API_KEY' };

/** The subset of Electron's safeStorage used here (injected so the store is unit-testable). */
export interface Crypto {
  isEncryptionAvailable(): boolean;
  encryptString(s: string): Buffer;
  decryptString(b: Buffer): string;
  getSelectedStorageBackend?(): string;
}

export class SecretStore {
  private file: string;

  constructor(
    dir: string,
    private crypto: Crypto,
    private platform: NodeJS.Platform = process.platform,
  ) {
    this.file = path.join(dir, 'secrets.json');
  }

  backend(): 'keychain' | 'basic' | 'unavailable' {
    if (!this.crypto.isEncryptionAvailable()) return 'unavailable';
    // Linux without a keyring falls back to a hard-coded password: report it, refuse to store
    if (this.platform === 'linux' && this.crypto.getSelectedStorageBackend?.() === 'basic_text') return 'basic';
    return 'keychain';
  }

  private read(): Partial<Record<SecretName, string>> {
    try {
      const raw = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      return raw && typeof raw === 'object' ? raw : {};
    } catch {
      return {};
    }
  }

  private write(d: Partial<Record<SecretName, string>>) {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const tmp = this.file + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(d), { mode: 0o600 });
    fs.renameSync(tmp, this.file);
  }

  status(): { backend: 'keychain' | 'basic' | 'unavailable'; keys: Record<SecretName, boolean> } {
    const d = this.read();
    return { backend: this.backend(), keys: { anthropic: Boolean(d.anthropic), openai: Boolean(d.openai) } };
  }

  set(name: SecretName, value: string) {
    if (this.backend() !== 'keychain') throw new Error('the OS keychain is not available: keys are not stored');
    const d = this.read();
    d[name] = this.crypto.encryptString(value).toString('base64');
    this.write(d);
    return this.status();
  }

  clear(name: SecretName) {
    const d = this.read();
    delete d[name];
    this.write(d);
    return this.status();
  }

  /** Decrypted keys as engine environment variables (unreadable entries are skipped). */
  env(): Record<string, string> {
    if (!this.crypto.isEncryptionAvailable()) return {};
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(this.read()) as [SecretName, string][]) {
      if (!(k in SECRET_ENV) || !v) continue;
      try {
        out[SECRET_ENV[k]] = this.crypto.decryptString(Buffer.from(v, 'base64'));
      } catch {
        /* key from another machine / user: ignore */
      }
    }
    return out;
  }
}
