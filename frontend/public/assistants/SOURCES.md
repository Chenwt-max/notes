# notes 助手立绘来源

当前素材为 `deepseek-poses.png`、`gpt-poses.png`、`claude-poses.png`、`grok-poses.png`、`glm-poses.png`、`kimi-poses.png`。2026-10-21 根据用户逐张提供的六幅人物参考，使用内置 `image_gen.imagegen` 制作透明静态多姿态图集。人物为 AI 辅助衍生图，不冒称原画的像素级复制。

每张 3 列 2 行，依次是原姿、招手、阅读、思考、疑惑、开心。轮盘中心点击切换静态姿态，提问和回答会选择对应姿态。没有连续肢体动画、视频素材或 DSH 动画运行管线。

本轮直接人物依据（用户提供的原图文件名）：

- DeepSeek：`ab6abf05ca1b67d36b0433fbb5b62d60.jpg`，蓝发鲸鱼女仆、单鳍鲸尾。
- GPT：`4d0d8d5284a5f81099e6f1925b94a82f.jpg`，白银龙女、紫瞳、白色旗袍式服装及角翼鳞尾。
- Claude：`777733bcc347fb2fd3cd4e3fa39f332d.jpg`，橘发、橘白长裙、花纹书本。
- Grok：`bb7c6f59dcaa656b938a415162028b8e.jpg`，金发双马尾、黑金裙与丰富金饰，按本轮原图保留一根大斧，不添加双挂斧。
- GLM：`a8866c9452fcd880946ab52076ed3bbd.jpg`，黑色长发、黑白 Z.AI 衣裙与蓝色宝石，无狐耳、狐尾。
- Kimi：`3e2e89e50899a51aba80cacaeed1337b.jpg`，白发紫瞳、K/月亮/音乐裙装与长笛配饰。

完整提示词、原图到输出路径及最终目标：`qa/pet-upgrade/pose-generation.json`。SHA-256、真实透明度、36 格主体边界及散点记录：`qa/pet-upgrade/atlas-verification.json`。边界复核脚本只读图片，不重编码或修改像素。部分生成图仍有少量主体外边缘杂点，未将其当作原画内容或精确抠图。

加载新图失败时，前五个角色使用既有 `*-actions.png` 静态帧；Kimi 使用 `kimi-portrait.png`。它们是已安装的图片回退，不触发联网生图。此前五角色图集的提示词记录在 `qa/notes-refresh/avatar-prompts.json`、`art-corrections.json`、`art-detail-prompts.json`，仅作为历史来源。

历史参考出处与署名线索保留如下：

- [TreapGoGo 鲸鱼娘](https://treapgogo.github.io/deepseek-whale-girl/index.html)。[CrossPet 来源说明](https://github.com/lokicorvus/crosspet/blob/main/characters/LICENSE.md)列原型上善无形、女仆二设 ZipZipPipe。
- [Mccrree 白银龙娘归档](https://github.com/Mccrree/chatgpt-dragon-character-assets)。社区原型归属 ZipZipPipe 的线索见上述 CrossPet 来源说明。
- ZipZipPipe 的 [Claude](https://xn--pssy23gqgbz2d718b.com/works/claude202610030001.html)、[Grok](https://xn--pssy23gqgbz2d718b.com/works/grok202610170001.html) 参考归档。历史 GLM 狐耳版已被本轮用户提供的无狐耳原图取代。

这些是非官方同人形象；图片权利归相应原作者，网站代码许可不覆盖图片。项目维护者已明确确认具有版权或必要授权，允许这些角色及全部姿态随 GitHub 源码和便携包公开分发；图片授权与代码 MIT 分开说明，见 ASSET_LICENSE.md。角色切换只改变外观与回答语气，实际 API 模型仍由设置决定。
