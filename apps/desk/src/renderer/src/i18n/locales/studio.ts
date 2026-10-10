// The one-page clip view (2026-10 review steps 4-8): transcript on open, clip info inline, the Studio list, the
// three-item nav and Orca-style attention. English, 简体中文, Français.

export const studioEn = {
  'st.restoreCuts': '{n, plural, one {Restore the cut} other {Restore # cuts}}',
};

export const studioZh: Record<keyof typeof studioEn, string> = {
  'st.restoreCuts': '{n, plural, one {恢复这处剪切} other {恢复 # 处剪切}}',
};

export const studioFr: Record<keyof typeof studioEn, string> = {
  'st.restoreCuts': '{n, plural, one {Rétablir la coupe} other {Rétablir # coupes}}',
};
