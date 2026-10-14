# shoper 的博客

使用 MkDocs Material 构建，以阅读为中心的个人博客。

## 写一篇文章

在下列目录或其子目录中新增一个 `.md` 文件即可。构建时会自动把文章加入对应专题、首页最新文章和文章归档，**无需修改 `mkdocs.yml` 或手工维护目录列表**。

| 存放目录 | 所属专题 |
| --- | --- |
| `docs/algo/`、`docs/solutions/` | 算法与题解 |
| `docs/csdiy/` | CS 自学 |
| `docs/technology/` | 技术实践 |
| `docs/views/`、`docs/blog/` | 随笔与看法 |

例如新增 `docs/technology/my-new-post.md`，最少只需写：

```markdown
# 我的新文章

从这里开始写正文。
```

文件名可以自由选择，不必延续 `p68.md` 这样的编号。也可以放在 `docs/technology/linux/my-new-post.md` 等子目录中；图片继续使用相对路径引用。各级目录中的 `index.md` 保留给目录页，不作为文章收录。

推荐在文章开头填写发布日期，其他信息按需补充：

```markdown
---
title: 我的新文章
date: 2026-10-14
summary: 一句话介绍这篇文章，按需填写。
---

# 我的新文章

从这里开始写正文。
```

- `title` 可省略：优先使用正文第一个一级标题，再回退到文件名。放在正文开头的一级标题会合并进页头，只显示一次。
- `date` 可省略：先取文件在 Git 中首次提交的日期，没有提交记录时取文件修改日期。建议显式填写 `YYYY-MM-DD`，固定发布日期；旧文章的日期格式仍兼容。
- `summary` 可省略：只有显式填写时才展示摘要，不会自动截取正文；也兼容 `description`。
- `draft: true` 标记草稿：不会生成文章页面，也不会进入首页、专题、归档或搜索。发布时删除此项或改为 `false`。
- 文章默认开启评论；需要关闭时填写 `comments: false`，也可显式写 `comments: true`。
- 系列文章可填写 `series: CSAPP`，再通过数字 `order: 2` 指定系列中的顺序。数字越小越靠前；没有 `order` 的文章排在其后，按日期从早到晚排列。普通文章无需填写。

旧文章沿用原有系列。新文章放入子目录但未填写 `series` 时，默认以最后一级父目录名作为系列，例如 `docs/technology/linux/my-new-post.md` 属于 `linux` 系列；显式填写 `series` 可以覆盖它。

首页和归档按发布日期排列。已有文章的文件位置和网址保持不变；网址关联的评论也会保留。后续若移动或重命名文章，网址会随之变化。

## 本地预览

在仓库根目录执行。Ubuntu / WSL：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m mkdocs serve
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m mkdocs serve
```

打开终端提示的本地地址（默认 `http://127.0.0.1:8000`）。保存文章后预览会自动重新构建。

## 检查与发布

```bash
python -m unittest discover -s tests
python -m mkdocs build
```

文章检查完成后，按平时的方式提交并推送到 `main`。现有 GitHub Actions 会自动构建并部署到 GitHub Pages。

自动索引逻辑位于 `hooks/blog.py`，在构建过程中扫描文章并生成列表，无需把生成的列表复制回 Markdown。日常写文章只需维护文章本身。

## 旧站评论

旧站 Valine 的 28 条评论（含 9 条回复）已保存为静态历史评论，新留言继续使用 Giscus。历史评论在页面中直接显示，不依赖 LeanCloud 继续提供服务，也无需登录 GitHub。

- 18 条评论对应 10 篇现有文章；留言板 6 条、友链 1 条。
- 另外 3 条的原文尚未在当前站找到，放在「旧站评论存档」页，保留来源链接。没有猜测它们属于哪篇新文章。
- 原文、昵称、`createdAt`、`insertedAt` 及回复 ID 保留在 `data/legacy-comments.json`。页面沿用 Valine 的 `insertedAt`（保存为 `published_at`），转换为北京时间显示；原始 ISO 时间不改写。
- 邮箱、IP、浏览器信息、ACL 和系统表不进入导入结果。评论 Markdown 经过 HTML 清洗后渲染。
- 三种旧表情使用原表情图片地址；如果图片服务不可用，替代文字仍保留原短码。

原始 LeanCloud 导出文件应放在项目外。之后如需导入更新的导出，在项目根目录运行：

```bash
python scripts/import_legacy_comments.py /path/outside/repository/export.tar.gz
python -m unittest discover -s tests
python -m mkdocs build --strict
```

导入器只读取压缩包中的 `Comment.*.jsonl`，不会解包或读取账户等系统表；也支持单独的 Comment JSON/JSONL 文件。先验证全部记录，再完整替换公开数据文件，重复导入不会追加重复评论。未知旧路径会报错，需先核对并更新 `data/legacy-comment-paths.json`。

映射文件只用于一次性的旧站迁移。新增文章和新评论不需要维护它；若移动承载旧评论的 Markdown 文件，应同步更新映射并重新导入。
