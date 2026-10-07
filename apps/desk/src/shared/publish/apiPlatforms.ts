// Official posting APIs (opt-in): the only way Reelfold ever publishes without her click, and only after she
// connected the account herself (OAuth in the system browser, scopes shown first). Everything else stays assisted:
// the form is filled, she presses Publish. Status per platform, as of this release:
export type ApiId = 'youtube' | 'tiktok' | 'x' | 'instagram';

export interface ApiPlatform {
  id: ApiId;
  /** board platforms it posts */
  platforms: string[];
  /** available: connect + auto-post works in this build; later: documented, not built (why in docs/PUBLISHING.md) */
  availability: 'available' | 'later';
  /** what she grants, shown before connecting */
  scopes: string[];
  docs: string;
}

export const API_PLATFORMS: ApiPlatform[] = [
  {
    id: 'youtube',
    platforms: ['youtube', 'youtube-shorts'],
    availability: 'available',
    scopes: ['https://www.googleapis.com/auth/youtube.upload'],
    docs: 'https://developers.google.com/youtube/v3/docs/videos/insert',
  },
  {
    id: 'tiktok',
    platforms: ['tiktok'],
    availability: 'later',
    scopes: ['video.upload', 'video.publish'],
    docs: 'https://developers.tiktok.com/doc/content-posting-api-get-started',
  },
  {
    id: 'x',
    platforms: ['x'],
    availability: 'later',
    scopes: ['tweet.write', 'media.write', 'users.read', 'offline.access'],
    docs: 'https://docs.x.com/x-api/media/upload-media',
  },
  {
    id: 'instagram',
    platforms: ['instagram'],
    availability: 'later',
    scopes: ['instagram_business_basic', 'instagram_business_content_publish'],
    docs: 'https://developers.facebook.com/docs/instagram-platform/content-publishing',
  },
];

export interface ApiStatusMsg {
  id: ApiId;
  availability: 'available' | 'later';
  platforms: string[];
  scopes: string[];
  /** her own OAuth client (YouTube: a Google Cloud "Desktop app" client) is saved in the keychain */
  hasClient: boolean;
  connected: boolean;
  connectedAt: string | null;
  /** post scheduled rows of these platforms through the API at their time */
  auto: boolean;
  /** the OS keychain can hold tokens (no keychain: connecting is refused) */
  keychain: boolean;
}
