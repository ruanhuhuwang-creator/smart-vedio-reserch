# 真实历史快照与 Git 记录

## 记录原则

本地 main 原先没有任何提交，远程也为空。因此没有可供恢复的第一至第四阶段 Git 历史。
本次使用本地分发包里真实保存的源码 ZIP 恢复两个旧版本，再接上当前工作区。
所有提交日期是实际整理日期 2026-10-22，没有回填开发日期，也没有依据当前代码虚构早期实现。

| 标签 | 内容与来源 | 原始源码 ZIP SHA256 |
| --- | --- | --- |
| phase5-windows | 首次验证完成的 Windows 便携版，release/20261021-111002/dist/SmartVision/_internal/frontend/dist/source-code.zip | 980bd399a431786d577282b25f5961aa549cb2896dda70a3dc63dfcf287ff065 |
| phase5-pts-fix | PTS 修复版，release/20261021-pts-hotfix/dist/SmartVision/_internal/frontend/dist/source-code.zip | be7941f29a3b1ce24849f4fbb0766ab4d6d30fcefaef9a07e45919d10f9f9f5e |
| phase5-counts-cancel | 2026-10-22 当前工作区，已验证的数量统计与单任务停止 | 当前 Git tree 即版本依据 |

两个 ZIP 中只取 SmartVision-source/ 下的项目源码，不把第三方源代码、视频或打包依赖加入仓库。
恢复时统一文本换行；补充相同的 LICENSE、.gitattributes 和必要目录 .gitkeep。
LICENSE 沿用此前分发包已声明的 AGPL v3，并取自随包 AGPL-3.0.txt；这些仓库元数据不宣称是早期开发行为。
原始 ZIP 及构建产物留在本机，不提交大文件；此表的路径是来源记录，不是 GitHub 下载链接。

## 对比方式

```powershell
git log --oneline --decorate
git show phase5-windows:backend/core/timestamps.py
git diff phase5-windows..phase5-pts-fix -- backend/core/timestamps.py backend/core/analyzer.py
git diff phase5-pts-fix..phase5-counts-cancel -- backend/services/tasks.py frontend/src/components/EventSearch.vue
git diff --stat phase5-windows..main
```

优先使用 git show/diff 阅读，不必切换当前工作区。需要运行旧版时，请使用独立目录、环境和数据库；
当前 v3 数据库不能交给旧版 EXE。用户视频、模型权重和数据不会随标签切换自动提供。

## 第一次到第四次迭代如何学习

按 CHANGELOG 和 VALIDATION、PHASE2_VALIDATION、PHASE3_VALIDATION、PHASE4_VALIDATION 阅读需求、模块和实际验证结果。
第五阶段快照已经包含此前阶段的能力，但不等于每个早期阶段的原始代码版本。
当前仓库保留这些文档作为真实过程记录，不创建不存在的早期版本标签。

## 后续记录规范

功能完成、验证后再提交；每次提交说明具体行为和测试结果。
修复、功能和文档尽量各自聚焦；重要可运行版本使用标签，并在 CHANGELOG 链接对应验收报告。
不要提交模型、私有视频、运行数据库、日志、密钥、虚拟环境和 node_modules。
