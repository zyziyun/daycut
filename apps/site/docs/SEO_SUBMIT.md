# 把 reelfold.com 提交给搜索引擎

网站部署到 reelfold.com 之后做一次（每个平台 10–20 分钟）。站点地图：`https://reelfold.com/sitemap-index.xml`
（含英文、中文、法文、西班牙文 40 个页面，每页都带其他语言版本的 hreflang）。`robots.txt` 已经指向它。

## 1. Google Search Console

1. 打开 https://search.google.com/search-console ，用你的 Google 账号登录，点「添加资源」。
2. 选「网域」(Domain)，填 `reelfold.com`。Google 给一条 TXT 记录。
3. 在 Cloudflare：reelfold.com → DNS → Records → Add record，类型 TXT，名称 `@`，内容粘贴那串 `google-site-verification=...`，保存。回到 Search Console 点「验证」（几分钟内生效，偶尔要等一小时）。
4. 左栏「站点地图」→ 填 `sitemap-index.xml` → 提交。
5. 左栏「网址检查」→ 分别输入 `https://reelfold.com/`、`https://reelfold.com/zh/`、`/fr/`、`/es/` → 「请求编入索引」。
6. 一周后看「网页」（有没有未编入索引的页面）和「核心网页指标」。

## 2. Bing Webmaster Tools（也供 DuckDuckGo、Ecosia、ChatGPT 搜索使用）

1. 打开 https://www.bing.com/webmasters ，登录（微软 / Google 账号都行）。
2. 最快：选「从 Google Search Console 导入」，授权后网站和站点地图一起导入，不用再验证。
   （或者手动添加 `https://reelfold.com`，用 DNS 验证：在 Cloudflare 加一条 Bing 给的 CNAME。）
3. 「站点地图」里确认有 `https://reelfold.com/sitemap-index.xml`，没有就手动提交。
4. 「URL 提交」里提交首页四个语言版本。

## 3. 百度搜索资源平台（百度站长）

1. 打开 https://ziyuan.baidu.com ，用百度账号登录（需要手机号实名）。
2. 「用户中心」→「站点管理」→「添加网站」，填 `https://reelfold.com`，协议选 https，站点属性选「科技 / 软件」。
3. 验证方式选「CNAME 验证」：在 Cloudflare 加一条 Baidu 给的 CNAME（例如 `xxxxxx.reelfold.com → ziyuan.baidu.com`），**代理状态设为「仅 DNS」（灰色云）**，回百度点完成验证。
4. 「普通收录」→「sitemap」提交 `https://reelfold.com/sitemap-0.xml`（百度不认 sitemap 索引文件，直接提交这个）。
5. 「普通收录」→「手动提交」贴入中文页面（每行一个）：
   ```
   https://reelfold.com/zh/
   https://reelfold.com/zh/course-slicing/
   https://reelfold.com/zh/podcast-clips/
   https://reelfold.com/zh/interview-clips/
   https://reelfold.com/zh/talking-head/
   https://reelfold.com/zh/studios/
   https://reelfold.com/zh/platforms/
   https://reelfold.com/zh/compare/capcut/
   ```
6. 说明：网站在海外（Cloudflare），**不需要 ICP 备案也能被百度收录**，但收录慢（几周）。上线后用国内手机网络打开 `/zh/` 看看速度；很慢的话再考虑国内 CDN（那时才需要备案）。

## 以后改了内容

- 新加页面：它会自动进站点地图，搜索引擎下次抓取时发现；想快一点就在 Google 「网址检查」和百度「手动提交」里提交这个 URL。
- 改了标题或中文标题：重新 `npm run build`，再跑 `npm run fonts:zh` 和 `npm run build`（中文标题字体是按用到的字裁剪的；`npm run check` 会提醒缺字）。
- 分享图（OG）改版：`npm run og`。
